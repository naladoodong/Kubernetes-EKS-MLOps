# ArgMax Mini 분석·보안·오류 대응 설계

## 1. 목적과 범위

이 문서는 Kubernetes/EKS 목표 아키텍처의 분석, 인증·인가, 보안 경계, 오류 처리, 관측 및 복구 설계를 정의한다. 운영 목표 설계이며 구현 완료를 주장하지 않는다. 48시간 구현 범위와 운영 목표는 분리하며, 새로운 RDB 엔티티·상태·인프라 제품을 추가하지 않는다.

## 2. 분석 환경

### 2.1 Experiment Analysis

MLflow는 run, hyperparameter, metric history, training environment 및 artifact lineage를 추적한다. MLflow는 business source of truth가 아니며, MLflow 기록 실패만으로 `TrainingJob`을 실패 처리하지 않는다. 최종 모델 metric 요약은 RDS `ModelVersion.metrics_json`을 API와 business summary의 기준으로 사용한다.

### 2.2 Dataset Analysis

| 계층 | 책임 |
|---|---|
| RDS | `row_count`, `column_count`, `DatasetColumn` 요약 |
| S3 | 처리된 Parquet와 profile |
| Glue | schema, catalog, partition metadata |
| Athena | 상세 분석 쿼리 |

Glue ETL을 별도로 도입하지 않는다.

### 2.3 Inference Analysis

InferenceLog는 S3의 Parquet 분석 데이터셋이다. 초기 Hive-style partition key는 `year/month/day/hour`이며, 예시는 다음과 같다.

```text
s3://argmax-mini/inference-logs/
  year=2026/month=08/day=07/hour=13/
```

`deployment_id`, `model_version_id`, `user_id`, `request_id`, `http_status`, `error_code`는 high-cardinality partition key가 아니라 Parquet column으로 저장한다. InferenceLog는 모델 품질 분석용 접근 통제 S3 데이터셋이며, logical field는 `request_id`, `deployment_id`, `model_version_id`, `user_id`, timestamp, `latency_ms`, `batch_size`, `http_status`, `error_code`, `input_payload_json`, `output_payload_json`이다. 정상 inference에서 ModelInterface input validation, serving, Gateway output validation이 모두 성공하면 metadata와 validated input/output을 저장한다. input validation 실패는 error/metadata만 기록한다. validation 뒤 serving 실패 또는 invalid serving response는 validated input과 error metadata만 기록하고 output payload와 invalid raw serving output은 저장하지 않는다. 모델별 schema 차이는 JSON-compatible payload로 표현한다.

이는 application/structured operational log와 별개다. operational log에는 raw inference feature·prediction, Dataset row 원문, credential, JWT/token, Authorization, Cookie, Secret, presigned URL, HTTP header 원문, 민감정보를 포함할 수 있는 stack trace를 기록하지 않는다. InferenceLog에도 Authorization, Cookie, JWT/token, credential, Secret, presigned URL, internal infrastructure URI, HTTP header 원문은 저장하지 않는다. durable delivery, Gateway crash 시 buffer loss, retention, sampling, field-level masking, 개인정보 분류와 DSAR 정책은 미해결 사항이다.

## 3. 인증, 인가와 신뢰 경계

특정 IdP 제품을 고정하지 않는다. 외부 인증 시스템이 제공한 `principal.user_id`를 내부 `User.id`에 매핑하며, client-supplied `user_id`, request body의 `user_id`, 임의 identity header는 신뢰하지 않는다.

초기 인가는 owner-based이다. `Dataset`과 `Model`은 각 `user_id`, `DatasetVersion`은 Dataset, `ModelVersion`은 Model, `TrainingJob`과 `InferenceDeployment`는 각 `user_id`의 ownership chain을 따른다. 존재하지 않거나 다른 사용자의 리소스는 모두 `404 RESOURCE_NOT_FOUND`로 처리한다. 인증 누락·실패는 401, 소유자가 가진 리소스의 상태 충돌은 409, 의미·schema 검증 오류는 422이다. 403은 향후 명시적 permission model 도입 시에만 검토한다.

공개 진입 경로는 `Route 53 → WAF → ALB → Backend API / Inference Gateway`이다. KServe는 internal ClusterIP Service만 사용한다. Inference Gateway는 business inference security boundary이고 Serving Runtime은 execution boundary다. presigned URL은 private bucket의 server-generated object key에만 발급하는 시간 제한 bearer capability이며 URL 자체를 로그에 남기지 않는다.

SQS message는 인증 principal이 아니다. Controller는 message payload만 신뢰하지 않고 RDS를 다시 조회한다. 사람 identity와 workload identity는 분리한다.

## 4. Workload identity와 권한

운영 기준 workload identity는 IRSA다. EKS Pod Identity는 지원되는 대안이지만 초기안에는 도입하지 않는다. 책임 하나당 dedicated ServiceAccount 하나와, 필요한 경우 최소 권한 IAM role 하나를 사용한다.

| 워크로드 | 최소 AWS 권한 경계 |
|---|---|
| Backend API | `datasets/original/*` upload에 필요한 PutObject, HeadObject, multipart 및 필요한 KMS 권한만. model/checkpoint/inference log 접근 금지 |
| Outbox Publisher | 대상 queue의 SQS `SendMessage`만 |
| Dataset Processing Controller | SQS consume만, dataset S3 data 접근 없음 |
| Dataset Processing Job | original read, processed write 및 필요한 KMS |
| Training Controller | training SQS consume만, model/checkpoint S3 write 없음 |
| Training Job | processed dataset read, checkpoint 및 model staging/final read-write, staging cleanup delete, 필요한 KMS |
| Deployment Controller | model artifact read-only |
| Inference Gateway | buffered logging 기준 `inference-logs/*` PutObject |
| Serving Runtime | model artifact read-only; RDS, SQS, Secrets Manager, Kubernetes API, S3 write/delete 금지 |
| ESO | Secrets Manager `GetSecretValue`, `DescribeSecret`, 필요한 `kms:Decrypt` |
| Fluent Bit | CloudWatch Logs write |

Node IAM role에 application의 broad S3/SQS/Secrets Manager 권한을 주지 않는다. IAM과 Kubernetes RBAC는 별개다.

### 4.1 Kubernetes RBAC

Backend API와 Outbox Publisher에는 Kubernetes API 권한이 없다. Dataset Controller는 `argmax-processing` namespace에서 Job의 create/get/list/watch/delete만, Training Controller는 `argmax-training`에서 Job create/get/list/watch/delete 및 Pod get/list/watch만 가진다. 둘 다 Secret, Node, 임의 Pod create/delete 권한은 없다.

Deployment Controller는 `argmax-serving`에서 KServe `InferenceService`의 create/get/list/watch/update/patch/delete, 필요한 Service의 get/list/watch, `argmax-tabular-runtime-v1` ClusterServingRuntime의 read-only 권한만 가진다. runtime mutation 권한은 없다. Kubernetes API가 필요 없는 Job, Gateway, Serving Runtime Pod는 `automountServiceAccountToken: false`를 설정한다.

### 4.2 VPC Network Architecture

운영 환경은 IPv4 기반 단일 VPC와 2개 Availability Zone(AZ)으로 구성한다. 각 AZ에는 Public, Private Application, Private Data Subnet을 하나씩 두므로 총 6개 subnet을 사용한다. CIDR 값은 구현 시점에 확정한다.

| subnet tier | 배치와 책임 | 인터넷 경로 |
|---|---|---|
| Public A/B | Internet-facing ALB, 각 AZ의 NAT Gateway | `0.0.0.0/0 → Internet Gateway` |
| Private Application A/B | EKS Managed Node Group, Karpenter GPU Node, 모든 application/Job/KServe/MLflow/observability workload | 같은 AZ NAT Gateway와 S3 Gateway Endpoint |
| Private Data A/B | RDS DB Subnet Group만 | VPC local route만; internet default route 없음 |

ALB는 두 Public Subnet에 걸친 하나의 logical load balancer다. EKS node와 Pod에는 public IP를 부여하지 않으며, RDS는 `Publicly Accessible=false`로 Private Data Subnet에만 둔다. Private Application A/B는 각각 NAT Gateway A/B를 사용해 cross-AZ NAT dependency를 피한다. NAT는 private workload의 필요한 AWS public API outbound를 위한 것이며 Private Data Subnet의 RDS outbound 경로가 아니다.

Route table은 다음을 기준으로 한다.

```text
Public A/B:              VPC CIDR → local, 0.0.0.0/0 → Internet Gateway
Private Application A:  VPC CIDR → local, S3 route → S3 Gateway Endpoint, 0.0.0.0/0 → NAT Gateway A
Private Application B:  VPC CIDR → local, S3 route → S3 Gateway Endpoint, 0.0.0.0/0 → NAT Gateway B
Private Data A/B:        VPC CIDR → local
```

S3 Gateway Endpoint를 Private Application route table의 baseline으로 사용한다. Dataset Processing Job, Training Job, Serving Runtime, Inference Gateway 등 승인된 VPC workload의 Original Dataset, Processed Parquet, Checkpoint, Model Artifact, InferenceLog S3 traffic은 이 endpoint로 NAT data processing path를 우회한다. 반대로 외부 End User의 presigned direct upload는 `End User → Internet → Amazon S3 public service endpoint` 경로이며 S3 Gateway Endpoint를 통과하지 않는다.

초기 baseline은 Interface VPC Endpoint를 사용하지 않는다. ECR API/DKR, STS, SQS, Secrets Manager, CloudWatch, EC2 등 필요한 AWS public API는 NAT를 통해 접근한다. NAT 비용, outbound 보안 요구 또는 특정 API의 private-only 요구가 실제로 확인되면 ECR API/DKR, STS, SQS, Secrets Manager, CloudWatch Logs를 우선 후보로 PrivateLink를 선택적으로 검토한다.

EKS API endpoint는 `endpointPrivateAccess=true`, `endpointPublicAccess=true`로 구성한다. public endpoint는 승인된 operator/CI CIDR만 허용하고, cluster 내부 node/controller는 private endpoint를 사용한다. VPC DNS는 `enableDnsSupport=true`, `enableDnsHostnames=true`를 사용한다. 초기 범위에는 private-only API endpoint, VPN, Direct Connect, bastion을 추가하지 않는다.

외부 진입은 `Internet → Route 53 → WAF → Internet-facing ALB → Backend API / Inference Gateway`다. AWS Load Balancer Controller는 Amazon VPC CNI Pod networking에 맞춰 ALB `ip` target type으로 두 workload Pod IP를 등록한다. KServe는 ALB target이나 public endpoint가 아니며 Inference Gateway 뒤의 cluster-local Service로만 호출한다.

MLflow는 Private Application Subnet 내부의 internal operational workload이며 public ALB target으로 노출하지 않는다. ML Engineer의 MLflow UI/API 접근은 End User public ingress와 분리된 authorized trusted internal/administrative network path를 전제로 한다. Client VPN, corporate/private network 또는 다른 private administrative connectivity는 가능한 integration option일 뿐, 현재 baseline은 특정 connectivity 제품을 채택하지 않는다. 따라서 VPN, Direct Connect, bastion을 추가하지 않는 기존 원칙과 충돌하지 않는다.

### 4.3 Security Group Boundary

Security Group은 VPC/node/database 수준의 network boundary를 담당한다.

```text
Internet -- TCP 443 --> ALB Security Group
ALB Security Group -- application traffic --> EKS node / workload network boundary
EKS application / node boundary -- TCP 5432 --> RDS Security Group
```

ALB SG는 Internet에서 TCP 443 ingress를 허용한다. TCP 80은 HTTPS redirect가 필요한 경우에만 추가한다. egress는 Backend API와 Inference Gateway target으로 제한한다. EKS network boundary는 ALB ingress, Kubernetes control plane↔node 필수 통신, workload→RDS, 허용 AWS endpoint 및 승인된 internal communication만 허용한다. RDS SG는 EKS application/node boundary만 TCP 5432 inbound로 허용하며 `0.0.0.0/0:5432`와 public inbound를 허용하지 않는다.

초기 baseline에서는 Security Groups for Pods를 도입하지 않는다. 책임은 다음과 같이 분리한다.

```text
Security Group = VPC / node / database network boundary
NetworkPolicy  = Pod-level ingress/egress segmentation
IAM / IRSA     = AWS API authorization
```

### 4.4 NetworkPolicy와 SecurityContext

Amazon VPC CNI native NetworkPolicy로 각 application namespace(`argmax-control`, `argmax-processing`, `argmax-training`, `argmax-serving`)에 default-deny ingress/egress를 둔다. DNS resolution을 위해 모든 application namespace workload에서 `kube-system`의 CoreDNS(`kube-dns`)로 UDP/TCP 53 egress만 명시적으로 허용한다. 특정 ClusterIP 주소는 문서에 hard-code하지 않는다.

그 밖의 egress는 workload별 필요한 대상만 허용한다.

| 워크로드 | 허용 egress |
|---|---|
| Backend API | RDS, S3, DNS |
| Outbox Publisher | RDS, SQS, DNS |
| Dataset Processing Controller | RDS, SQS, Kubernetes API, DNS |
| Dataset Processing Job | RDS, S3, DNS |
| Training Controller | RDS, SQS, Kubernetes API, DNS |
| Training Job | RDS, S3, MLflow, DNS |
| Deployment Controller | RDS, S3, Kubernetes API, DNS |
| Inference Gateway | RDS, KServe internal Service, inference logging path, DNS |
| Serving Runtime | model artifact S3, DNS |

Kubernetes API egress는 Dataset Processing Controller, Training Controller, Deployment Controller에만 허용한다. Backend API, Outbox Publisher, Dataset Processing Job, Training Job, Inference Gateway, Serving Runtime은 Kubernetes API egress가 없으며 `automountServiceAccountToken: false` 원칙과 일치한다. Deployment Controller에는 SQS egress를 허용하지 않는다. Prometheus scrape ingress도 필요한 대상에만 허용한다. ESO와 Fluent Bit은 application namespace와 분리된 platform add-on namespace profile에서 각각 Secrets Manager와 CloudWatch Logs, 그리고 DNS egress만 허용한다. IAM이 허용하지 않은 dependency를 NetworkPolicy에서 넓게 허용하지 않으며, IAM은 AWS API authorization이고 NetworkPolicy는 network reachability라는 별도 보안 계층이다. Security Group은 이 Pod-level 방어 계층의 대체재가 아니다. Cilium과 service mesh는 도입하지 않는다.

모든 application/Job workload는 non-root, privilege escalation 금지, capability `ALL` drop, `RuntimeDefault` seccomp를 사용한다. privileged, hostNetwork, hostPID, hostIPC, hostPath는 금지한다. 가능한 workload에는 read-only root filesystem을 적용하고 `/tmp`, `/work`, `/model-cache` 등의 쓰기 경로는 `emptyDir`를 사용한다. GPU Job도 privileged가 아니며 NVIDIA device plugin의 `nvidia.com/gpu` resource로 GPU를 할당한다.

## 5. Secrets

Secret 경로는 `AWS Secrets Manager → ESO → Kubernetes Secret → Pod`이다. ESO만 Secrets Manager를 직접 읽고 일반 application workload는 Kubernetes Secret만 사용한다. AWS Access Key를 Kubernetes Secret에 저장하지 않으며 IRSA를 사용한다.

Secret은 하나의 공용 묶음이 아니라 consumer/dependency별(control-plane DB, job DB, inference read-only DB, MLflow, Grafana, external integration)로 분리한다. Serving Runtime에는 DB Secret이 없다.

회전 credential은 ESO `refreshPolicy: Periodic`, 초기 `refreshInterval: 5m`을 사용하고 low-change secret은 1h를 사용한다. DB는 alternating-users rotation(예: 30일)을 사용하며, ESO refresh latency와 workload credential adoption의 합은 rotation interval보다 충분히 작아야 한다. Deployment는 ESO 동기화 후 rolling restart가 필요하지만 그 trigger owner(manual, CI/CD·GitOps, separate controller)는 미해결이다. long-running Job은 회전만으로 강제 restart하지 않으며 다음 Job이 최신 Secret을 사용한다. ESO의 일시 실패 시 last-known Kubernetes Secret은 유지하지만, Secret이 전혀 없는 신규 workload는 fail closed한다.

## 6. 오류 계약

오류 category는 RDB column이 아니며 기존 domain `error_code`와 함께 사용한다: `VALIDATION_ERROR`, `AUTHENTICATION_ERROR`, `RESOURCE_CONFLICT`, `DATA_INTEGRITY_ERROR`, `CONFIGURATION_INTEGRITY_ERROR`, `RETRYABLE_INFRASTRUCTURE_ERROR`, `EXECUTION_FAILURE`, `TIMEOUT`, `SERVING_RESPONSE_ERROR`.

| HTTP | 의미 |
|---|---|
| 400 | malformed/basic request |
| 401 | authentication failure |
| 404 | nonexistent 또는 cross-user resource |
| 409 | resource/state conflict |
| 413 | payload too large |
| 422 | semantic/schema validation |
| 500 | unexpected application failure |
| 502 | invalid serving response |
| 503 | dependency, serving 또는 configuration unavailable |
| 504 | synchronous serving timeout |

애플리케이션 오류는 `error.code`, 안전한 `message`, `request_id`를 가진 공통 envelope로 응답한다. SQL, stack trace, secret, presigned URL, internal S3 URI, Kubernetes detail, raw exception은 노출하지 않는다. WAF/ALB 차단 응답은 이 contract 바깥일 수 있다.

## 7. Retry와 reconciliation

Retry는 operation-specific이다. uncertain side effect는 실제 상태를 먼저 reconcile하며 retry 중 deadline을 reset하지 않는다. non-idempotent write의 blind retry, infinite hot loop는 금지하고, exhaustion reason을 보존한다.

Outbox는 `published_at`, `retry_count`, `last_error`, `next_attempt_at`을 이용한 DB-driven exponential backoff를 사용한다. SQS는 at-least-once wake-up일 뿐이며 duplicate publish/delivery를 예상한다. consumer는 `event_id`, aggregate/resource ID, conditional update, deterministic Kubernetes resource name으로 멱등성을 만든다. 예를 들어 Dataset Processing Controller는 `dataset_version_id`의 `UPLOADED → PROCESSING` conditional update와 deterministic processing Job 이름을 사용하여 PROCESSING/READY/FAILED duplicate effect를 만들지 않는다. 별도 processed-event table은 추가하지 않는다.

| 상황 | owner / 처리 | business state |
|---|---|---|
| API validation | API / 재시도 없음 | 안전한 4xx 반환 |
| Outbox publish·SQS delivery 불확실성 | publisher·consumer / backoff와 event_id reconciliation | 중복 효과 없음 |
| multipart complete 불확실성 | upload 흐름 / object 상태 확인 후 재개 | 실제 object 상태를 기준으로 함 |
| Dataset Processing transient·deterministic failure | processing controller / 전자는 제한 retry, 후자는 실패 종결 | 기존 상태 전이 준수 |
| GPU quota wait | scheduler/controller / 관측과 deadline | 임의 실패 전이 없음 |
| Training transient·deterministic failure, Job lost | training controller / 기존 semantic retry와 `backoffLimit: 1`, reconciliation | 기존 상태 전이 준수 |
| Deployment create | deployment controller / reconciliation과 deadline | create/recovery failure·timeout만 FAILED |
| Deployment update | deployment controller / last applied configuration rollback | rollback 성공 READY, rollback failure·timeout만 FAILED |
| Deployment delete | deployment controller / reconciliation과 deadline | 기존 삭제 상태 전이 준수 |
| Gateway → KServe failure | Gateway / automatic retry 0 | HTTP error contract 반환 |
| MLflow logging failure | Training Job / business retry와 분리 | 단독으로 TrainingJob 실패 아님 |
| InferenceLog delivery failure | Gateway / buffered delivery 상태 기록 | durability는 미해결 |

Deployment는 일반 retry 횟수로 단순화하지 않고 reconciliation + deadline + rollback을 사용한다. scale-to-zero를 사용하지 않으며 활성 `InferenceDeployment.min_replicas >= 1`이다.

## 8. 관측과 감사

관측은 Metrics(Prometheus/CloudWatch), application logs(stdout/stderr → Fluent Bit → CloudWatch Logs), Audit(RDS AuditLog), training execution history(`TrainingJobEvent`), inference analytics(S3 InferenceLog)로 분리한다. distributed tracing backend는 초기 도입하지 않는다.

동기 HTTP 요청은 `request_id`를 생성해 내부 동기 호출에 전파한다. Outbox/SQS 등 비동기 workflow는 `event_id + aggregate/resource ID`를 사용한다. 별도 `correlation_id`는 초기 도입하지 않는다.

Prometheus label에는 request/user/resource UUID, S3 URI/key, raw Kubernetes resource name을 넣지 않는다. `service`, `environment`, `http_method`, `route_template`, `status_class`, `operation`, `result`, `status`, `error_category`, bounded `error_code`, `event_type`, `queue`, `algorithm`, `deployment_operation`만 사용한다. 개별 UUID 분석은 logs, RDS events, Athena에서 한다.

주요 metric 예시는 `http_requests_total`, `http_request_duration_seconds`, `http_requests_in_flight`, `inference_requests_total`, `inference_request_duration_seconds`, `serving_upstream_errors_total`, `invalid_serving_responses_total`, `outbox_publish_total`, `outbox_publish_retry_total`, `outbox_oldest_pending_age_seconds`, `outbox_pending_events`, `controller_reconcile_total`, `controller_reconcile_duration_seconds`, `controller_reconcile_errors_total`, `inference_log_records_total`, `inference_log_delivery_errors_total`, `inference_log_buffered_records`다.

구조화 로그에는 timestamp, level, service, event, request_id(해당 시), event_id(비동기 시), resource_type, resource_id, error_category, error_code를 기록한다. resource ID는 log field에는 허용하지만 metric label에는 금지한다. Secret, token, raw Dataset row, raw inference input/output을 포함한 raw user data는 기록하지 않는다.

AuditLog는 actor 중심 관리 행위를 기록하고, `TrainingJobEvent`는 training 실행 이력을 기록한다. HTTP 관리 행위는 `actor_type=USER`, 인증된 `actor_user_id`, HTTP `request_id`를 사용한다. Controller/Cleanup/Reconciler가 수행한 감사 대상 관리 행위는 `actor_type=SYSTEM`, `actor_user_id=NULL`, `request_id=NULL`이다. 모든 reconcile loop나 모든 training state transition을 AuditLog에 복제하지 않는다.

감사 대상 business mutation이 성공하는 경우에는 business mutation과 `AuditLog(result=SUCCESS)`를 같은 PostgreSQL transaction으로 commit한다. SUCCESS AuditLog INSERT가 실패하면 transaction 전체를 rollback하고 business mutation을 성공으로 처리하거나 성공 응답을 반환하지 않는다. 즉, required SUCCESS AuditLog가 없는 committed business mutation은 허용하지 않는다.

이미 거절되었거나 rollback된 요청의 `AuditLog(result=FAILURE)`는 별도 best-effort transaction으로 기록한다. FAILURE AuditLog 기록이 실패해도 원래 API/business failure 결과는 바꾸지 않는다. 이 실패는 structured application log, `audit_write_failures_total` metric, operator alert로 관측한다.

모든 FAILED resource를 page하지 않는다. invalid CSV, checksum mismatch, unsupported feature, 단발 CUDA OOM, user cancellation 같은 domain/user failure는 상태·오류·로그·metric만 남긴다. RDS unavailable, Outbox/SQS backlog, controller reconcile 또는 ESO sync의 지속 실패, deployment rollback failure, `SERVING_CONFIGURATION_INVALID`, 반복 `INVALID_SERVING_RESPONSE`은 Alertmanager/CloudWatch Alarm의 대상이다. threshold, routing, on-call destination은 미해결이다.

## 9. 장애 복구

| 장애 | 즉시 처리와 복구 |
|---|---|
| RDS | Multi-AZ DB instance failover 동안 write와 Gateway authorization은 fail closed, controller는 stale state로 mutate하지 않음. 깨진 connection을 폐기하고 RDS DNS endpoint로 새 connection을 만든 뒤 actual state reconcile |
| S3/SQS/Controller/Kubernetes API | 불확실한 결과를 즉시 business failure로 단정하지 않고 object, event, Kubernetes resource를 reconcile |
| Dataset Processing Pod, GPU node/Training Pod, Kubernetes Job | controller가 기존 deadline·semantic retry 및 상태 전이 기준으로 reconcile |
| KServe resource lost/drift/delete | deployment controller가 실제 resource와 DB intent를 reconcile; update 오류는 rollback 우선 |
| Serving unavailable/timeout·invalid response | Gateway automatic retry 없이 503/504 또는 502 contract 반환, 반복 시 alert |
| InferenceLog delivery | buffered logging의 delivery error를 기록; durable delivery는 미해결 |
| Secrets Manager/ESO | last-known Secret 유지, 신규 workload는 Secret 부재 시 fail closed |
| MLflow | 관측 실패로만 기록, 단독으로 TrainingJob 실패 처리하지 않음 |
| Observability path | 관측 경로 장애와 business source of truth를 분리하고 platform-actionable 상태를 alert |

운영 RDS PostgreSQL은 Multi-AZ DB instance deployment를 사용한다. Primary와 synchronous standby의 AZ 배치는 RDS가 관리하며 failover 후 역할이 바뀔 수 있으므로 특정 AZ를 static primary로 문서화하지 않는다. failover가 0초 투명 복구를 보장하지는 않는다. DB transaction 결과가 불확실하면 blind mutation retry를 하지 않고 실제 business state를 다시 확인한다.

RDS outage 중 final checkpoint S3 upload는 성공했으나 `TrainingCheckpoint` INSERT가 실패할 수 있다. 이 경우 final S3 object만 있고 DB row가 없는 checkpoint는 unpublished이며 retry Pod resume 대상으로 쓰지 않는다. RDS 복구 후에는 final object의 size/checksum/manifest를 검증하고 TrainingJob lock을 획득한 뒤 같은 `checkpoint_id` row를 조회한다. row가 없으면 sequence number를 할당하여 동일 `checkpoint_id`로 INSERT를 재시도한다. 새 checkpoint_id를 만들지 않는다. 반대로 DB row가 있으나 S3 final object가 없거나 mismatch면 `is_resumable=false`, `CHECKPOINT_INVALIDATED`로 처리한다. 별도 automatic S3 orphan scanner가 있다고 주장하지 않는다.

## 10. 미해결 사항

1. Gateway crash 시 flush되지 않은 로그 손실을 막을 InferenceLog durable delivery(queue/stream) 방식
2. Secret 변경 뒤 Deployment rolling restart trigger owner(manual, CI/CD·GitOps, separate controller)
3. RDS append-only AuditLog의 archive와 physical purge lifecycle
4. CloudWatch Logs, AuditLog, InferenceLog의 구체적 retention 기간과 InferenceLog sampling·field-level masking·개인정보 분류·DSAR 정책
5. alert threshold, routing, on-call destination
6. RDS DR, RTO, RPO, backup retention/PITR 및 cross-region recovery strategy (multi-region active-active는 초기 범위 밖)
7. MLflow 같은 private tool의 internal administrative connectivity 구체 방식
