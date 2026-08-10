# ArgMax Mini System Context

## 1. 문서 목적

이 문서는 ArgMax Mini의 운영 목표 아키텍처를 정의한다.

ArgMax Mini는 사용자가 CSV 또는 Excel 형식의 테이블 데이터를 업로드하고, 해당 데이터로 AI 모델 학습을 요청하며, 학습된 모델을 API로 배포·호출할 수 있는 플랫폼이다.

본 문서는 다음을 다룬다.

- 시스템 경계와 사용자 유형
- Control Plane과 Data Plane 구분
- Kubernetes 내부 구성요소와 AWS Managed Service 역할
- 동기·비동기 처리 경계
- 데이터 업로드, 학습, 배포, 추론의 주요 흐름
- 보안, 관측, 분석 및 운영 경계
- 운영 목표 아키텍처와 로컬 평가 구현 범위의 차이

> 운영 목표 아키텍처와 과제 구현 범위는 구분한다. 운영 환경은 AWS EKS 기반으로 설계하지만, 48시간 과제의 실제 구현 범위는 Docker Compose 기반 로컬 실행 환경과 Dataset 중심 CRUD API다.

---

## 2. 시스템 범위

### 2.1 시스템이 제공하는 기능

- Dataset 생성·조회·수정·삭제·복원
- DatasetVersion 생성 및 파일 버전 관리
- 최대 2 GB CSV/Excel 업로드
- 원본 파일 검증 및 Parquet 변환
- 학습 요청 생성·조회·취소
- GPU 기반 장기 학습
- Checkpoint 및 Model Artifact 저장
- Model 생성·조회·수정·삭제·복원
- 신규 Model과 최초 TrainingJob의 원자적 생성
- 기존 Model 대상 재학습 및 ModelVersion 관리
- 모델별 입출력 인터페이스 관리
- 모델 배포 및 동기식 추론 API 제공
- 추론 로그의 S3 적재 및 Athena 분석
- Kubernetes, GPU, 애플리케이션 및 AWS 서비스 관측

### 2.2 시스템 범위 밖

- 인증 시스템 자체 구현
- 전체 MLOps 운영 환경의 실제 배포
- EKS, KServe, Karpenter, MLflow의 실제 구축
- 장기 스트리밍 또는 LLM 추론
- 실시간 feature store
- 온라인 학습
- 자동 하이퍼파라미터 최적화 플랫폼
- 멀티리전 Active-Active 구성

---

## 3. 사용자와 외부 시스템

### 3.1 외부 사용자

#### 엔드유저

- Dataset을 생성하고 파일을 업로드한다.
- 준비된 DatasetVersion을 선택해 학습을 요청한다.
- Model과 ModelVersion을 조회·삭제·복원한다.
- 배포된 모델을 API로 호출한다.

#### 내부 사용자

- ML Engineer는 MLflow에서 학습 Run, 하이퍼파라미터, metric history, environment, artifact lineage를 분석하고 Athena에서 processed Dataset 및 InferenceLog의 input/output distribution과 모델 품질 개선을 분석한다.
- Data Analyst는 S3에 적재된 Parquet 및 InferenceLog를 Athena로 분석한다.
- Platform Operator는 Grafana, Prometheus 및 CloudWatch로 시스템 상태를 관찰한다.

MLflow는 EKS Private Application Subnet의 private workload로 유지하며 public End User ingress나 ALB target으로 노출하지 않는다. ML Engineer의 접근은 authorized trusted internal/administrative network path를 전제로 하고, 구체적인 private connectivity 방식은 운영 환경 integration concern으로 남긴다.

### 3.2 외부 시스템

- Amazon Route 53
- AWS WAF
- Application Load Balancer
- Amazon RDS for PostgreSQL
- Amazon S3
- Amazon SQS
- Amazon ECR
- Amazon Athena
- AWS Glue Data Catalog
- AWS Secrets Manager
- Amazon CloudWatch
- GitHub Actions
- Argo CD

---

## 4. 설계 원칙

### 4.1 Control Plane과 Data Plane 분리

Control Plane은 비즈니스 상태와 실행 의도를 관리한다.

Data Plane은 실제 파일 처리, GPU 학습 및 추론을 수행한다.

### 4.2 API와 장기 작업 생명주기 분리

대용량 파일 처리와 12~24시간 GPU 학습은 API Pod 내부에서 실행하지 않는다.

API는 작업을 수락하고 상태 리소스를 생성하며, 실제 처리는 Kubernetes Job이 수행한다.

### 4.3 OLTP와 OLAP 분리

- OLTP: RDS PostgreSQL
- 대용량 객체: S3
- OLAP: S3 + Athena + Glue Data Catalog

추론 요청·응답 로그는 RDB 일반 테이블로 저장하지 않는다.

### 4.4 기준 저장소 명확화

- 비즈니스 상태의 기준: RDS PostgreSQL
- 대용량 객체의 기준: S3
- 비동기 메시지 전달: SQS
- 실험 추적: MLflow
- Kubernetes 실행 상태: Kubernetes API

### 4.5 운영 설계와 로컬 구현 분리

운영 아키텍처의 AWS 기능을 실제 구현 완료로 표현하지 않는다.

로컬 평가 환경은 AWS 계정이나 자격증명 없이 다음 명령으로 실행되어야 한다.

```bash
docker compose up -d
```

### 4.6 운영 Network와 RDS HA 기준

운영 목표는 IPv4 단일 VPC와 2개 AZ를 사용한다. 각 AZ는 Public, Private Application, Private Data Subnet으로 나뉘며 총 6개 subnet이다. Internet-facing ALB와 AZ별 NAT Gateway는 Public Subnet, public IP가 없는 EKS node/Pod는 Private Application Subnet, `Publicly Accessible=false` RDS는 Private Data Subnet의 DB Subnet Group에 둔다. Private Application Subnet은 같은 AZ NAT Gateway와 S3 Gateway Endpoint를 사용하며, Private Data Subnet에는 internet default route가 없다.

외부 presigned upload는 Internet을 통해 Amazon S3 public service endpoint로 직접 전송되고 S3 Gateway Endpoint는 VPC 내부 workload의 S3 path에만 사용된다. EKS API는 private+restricted-public endpoint를 사용하며, ALB는 `ip` target type으로 Backend API와 Inference Gateway Pod에만 연결한다. KServe는 cluster-local boundary를 유지한다.

RDS PostgreSQL은 Business State와 Execution Intent의 source of truth이며, 운영 HA는 Multi-AZ DB instance deployment(Primary + synchronous standby)를 사용한다. DR/RTO/RPO와 cross-region recovery는 별도 미해결 운영 항목이다.

---

## 5. 전체 아키텍처

```text
Client
  │
Route 53
  │
AWS WAF
  │
Application Load Balancer
  ├───────────────────────────────────────────────┐
  │                                               │
Backend API                                Inference Gateway
  │                                               │
  │                                       RDS metadata lookup
  │                                               │
  │                               cluster-local KServe ClusterIP Service
  │                                               │
  │                                       Model Serving Pod
  │                                               │
  │                                             S3 Artifact
  │
RDS PostgreSQL
  │
  ├── Outbox Publisher ──> SQS ──> Dataset Processing Controller
  │                                      │
  │                                      └──> Dataset Processing Job
  │                                                  │
  │                                                  └──> S3
  │
  └── Outbox Publisher ──> SQS ──> Training Controller
                                         │
                                         └──> Training Job
                                                   │
                                                   ├──> Karpenter GPU Node
                                                   ├──> S3 Checkpoint/Artifact
                                                   └──> MLflow

Prometheus / Alertmanager / Grafana
  ├── Kubernetes metrics
  ├── Application metrics
  ├── KServe metrics
  ├── Karpenter metrics
  └── GPU metrics via DCGM Exporter

CloudWatch
  ├── ALB
  ├── RDS
  ├── SQS
  ├── S3
  ├── EKS Control Plane
  └── Centralized container logs

S3 Inference Logs
  └── Glue Data Catalog
        └── Athena
```

---

## 6. Control Plane

### 6.1 Backend API

기술: FastAPI, SQLAlchemy, Pydantic v2

책임:

- Dataset CRUD
- DatasetVersion 메타데이터 관리
- UploadSession 생성 및 완료 처리
- TrainingJob 생성·조회·취소
- Model 및 ModelVersion 관리
- 신규 Model과 최초 TrainingJob을 동일 트랜잭션에서 생성
- READY DatasetVersion과 Model 소유권을 검증한 후 TrainingJob 생성
- InferenceDeployment 생성 요청과 사용자·환경별 소유권 관리
- Soft Delete 및 30일 복원 정책
- 사용자 요청 멱등성 처리
- AuditLog 기록

### 6.2 Outbox Publisher

책임:

- PostgreSQL의 발행 가능 OutboxEvent 조회
- `published_at IS NULL AND next_attempt_at <= now()` 조건 적용
- `FOR UPDATE SKIP LOCKED` 기반 batch claim
- SQS 발행
- 성공 시 `published_at` 갱신
- 실패 시 `retry_count`, `last_error`, `next_attempt_at` 갱신 및 지수 백오프 적용
- 발행 완료 이벤트는 30일 보존 후 Cleanup Job이 배치 삭제
- 중복 발행 가능성을 고려한 Consumer 멱등성 전제

### 6.3 Dataset Processing Controller

책임:

- SQS 처리 메시지 소비
- DatasetVersion 상태 확인
- 중복 실행 방지
- 재시도 가능 여부 판단
- Dataset Processing Job 생성
- Job 상태 감시 및 reconciliation
- timeout·고아 Job 탐지

Controller는 파일을 직접 파싱하지 않는다.

### 6.4 Training Controller

책임:

- SQS를 wake-up signal로 소비하고 `training_job_id`로 RDS 최신 상태·설정을 재조회
- 60초 Periodic Reconciler로 QUEUED, SCHEDULING, RUNNING, CANCEL_REQUESTED 상태별 최대 100건을 재검사
- scheduling 직전 authoritative GPU quota 검증; quota 부족은 QUEUED 유지·QUOTA_WAITING 기록·SQS 메시지 삭제
- 조건부 `QUEUED → SCHEDULING` 갱신과 결정적 `training-{training_job_id}` 이름으로 Kubernetes Training Job 생성
- 중복 Job 생성 방지 및 SCHEDULING/RUNNING 고아 Job·timeout reconciliation
- QUEUED, SCHEDULING, RUNNING 상태의 취소 요청 반영
- SCHEDULING 중 취소 시 Job 생성을 중단하거나 생성 직후 terminal 상태를 확인한 뒤, terminal이 아니면 Kubernetes Job 삭제
- Job 상태 감시 및 reconciliation
- retryable/non-retryable 오류 구분
- Kubernetes 상태와 RDB 상태 보정
- Pod Running 관찰 후 `SCHEDULING → RUNNING`, Kubernetes Job Complete/Failed 관찰 후 성공 불변조건을 검증하여 `RUNNING → SUCCEEDED` 또는 `FAILED` 전이
- Job Complete 시 `TRAINING_RESULT_FINALIZATION_STARTED`를 기록하고 최대 10분간 후보 finalization 대기
- READY·CREATING·FAILED ModelVersion과 생성 전 실패 후보를 집계하여 부분 성공 또는 `ALL_MODEL_CANDIDATES_FAILED`, `NO_MODEL_CANDIDATE_PRODUCED`, `TRAINING_RESULT_INCOMPLETE`를 판정
- 생성 전 실패 이벤트는 candidate_number 기준으로 중복 제거하고, 같은 candidate의 ModelVersion 결과와 이중 집계하지 않음
- Kubernetes Job 종료 뒤 잔존 CREATING ModelVersion reconciliation, 유효 final artifact의 READY finalization 재시도, `MODEL_ARTIFACT_LOST`와 30분 CREATING timeout 처리
- 10분 결과 확정 timeout 시 잔존 CREATING 후보를 `TRAINING_RESULT_FINALIZATION_TIMEOUT`으로 FAILED 처리하고 TrainingJob FAILED 뒤 READY 시간 역전을 차단
- CANCEL_REQUESTED에서 Kubernetes Job terminal 상태를 삭제보다 먼저 확인하고, Complete면 결과 확정, 실행 중이면 graceful termination, 삭제 완료면 잔존 CREATING 실패 정리 뒤 CANCELLED 전이
- checkpoint resume과 retry Pod의 기존 Job deadline 공유
- 동일 TrainingJob retry Pod의 MLflow parent Run 재사용

SQS는 영속적 작업 기준이 아니며 RDS와 Reconciler가 메시지 누락·DLQ 이동·Controller 장애를 복구한다. DLQ는 운영 조사와 격리 수단이지 유일한 복구 경로가 아니다.

### 6.5 Deployment Controller

책임:

- InferenceDeployment 생성 요청 감지
- KServe InferenceService 생성·변경·삭제
- KServe readiness 확인
- InferenceDeployment 상태 갱신
- RDB와 KServe 상태 reconciliation

### 6.6 Inference Gateway

책임:

- 인증·인가
- Model 소유권 및 삭제 상태 확인
- InferenceDeployment 상태 확인
- ModelInterface 기반 JSON Schema 검증
- 외부 요청을 KServe 요청 형식으로 변환
- timeout 및 공통 오류 응답
- `request_id` 생성 및 내부 동기 호출에 전파
- 추론 로그 문맥 생성
- public endpoint가 아닌 cluster-local KServe ClusterIP Service 호출

장기 스트리밍 추론은 현재 범위에서 제외한다.

---

## 7. Data Plane

### 7.1 Dataset Processing Job

책임:

- S3 원본 다운로드
- 파일 크기 검증
- MIME type 및 magic number 검증
- checksum 검증
- CSV/Excel 파싱
- Excel 첫 번째 시트 처리
- 압축 해제 크기 제한
- 행·열 수 제한
- Parquet 변환
- 컬럼 스키마 및 통계 추출
- 처리 결과 S3 저장
- DatasetColumn 및 DatasetVersion 갱신
- 성공 시 `READY`, 실패 시 `FAILED`

### 7.2 Training Job

책임:

- S3의 Parquet 데이터 다운로드
- GPU 학습 실행
- MLflow Run 생성 및 기록
- 주기적 S3 Checkpoint 저장
- 평가 지표 계산
- 후보별 artifact staging·final immutable publish
- ModelVersion 및 ModelInterface finalization
- 실행 중 publish 오류에 따른 ModelVersion FAILED
- ModelVersion 생성 전 직렬화·로컬 ModelInterface 검증 오류는 `CANDIDATE_TRAINING_FAILED`로 기록
- checkpoint_id를 사전 생성해 staging·final S3 경로, manifest, TrainingCheckpoint.id에 동일하게 사용
- 학습 결과와 내부 오류 기록

초기 Algorithm Registry는 `XGBOOST_CLASSIFIER`, `XGBOOST_REGRESSOR`만 지원한다. Training Runtime은 GPU-capable XGBoost의 `tree_method=hist`, `device=cuda`(또는 동등한 공식 GPU 설정)를 강제하며 사용자 CPU override를 허용하지 않는다. `nvidia.com/gpu` request=limit의 Pod allocation과 실제 CUDA execution을 함께 보장한다. Processed Parquet는 memory-efficient quantile input path로 읽고, GPU external-memory training은 실제 VRAM pressure가 확인될 때의 확장 경로로 둔다. RAPIDS/cuDF/cuML/RMM과 multi-GPU distributed XGBoost는 초기 baseline이 아니다.

Training Job은 실행 결과 데이터를 기록하며 Kubernetes Job/Pod 생명주기 관찰에 따른 TrainingJob 상태 전이는 Training Controller가 수행한다. Pod retry는 기존 후보의 ModelVersion과 immutable artifact 경로를 재사용한다.

### 7.3 KServe Model Serving Pod

책임:

- S3 Model Artifact 로딩
- Serving Runtime 실행
- 모델 종속 전처리·후처리
- 실제 추론 수행
- health 및 readiness 제공
- 모델별 replica 관리 및 autoscaling

초기 Serving Runtime은 XGBoost `model.json` artifact만 CPU에서 실행한다. generic scikit-learn/joblib artifact와 runtime은 초기 범위 밖이며, KServe는 Inference Gateway 뒤의 cluster-local serving boundary로만 사용한다.

---

## 8. Kubernetes와 AWS Managed Service 경계

| 영역 | Kubernetes | AWS Managed Service |
|---|---|---|
| 외부 요청 | Backend API, Inference Gateway | Route 53, WAF, ALB |
| 메타데이터 | DB client | RDS PostgreSQL |
| 파일 업로드 | UploadSession API | S3 Single PUT 또는 Multipart Upload |
| 파일 처리 | Controller + Job | SQS, S3 |
| 학습 | Training Controller + GPU Job | SQS, S3, ECR |
| 모델 서빙 | KServe, Inference Gateway | ALB, S3 |
| 분석 | 로그 producer | S3, Glue, Athena |
| 메트릭 | Prometheus, Grafana | CloudWatch |
| 중앙 로그 | Fluent Bit | CloudWatch Logs |
| 비밀정보 | External Secrets Operator | Secrets Manager |
| 이미지 배포 | Kubernetes image pull | ECR |

---

## 9. 노드 구성

### 9.1 Managed Node Group

상시 워크로드:

- Backend API
- Dataset Processing Controller
- Training Controller
- Deployment Controller
- Inference Gateway
- Outbox Publisher
- MLflow
- Prometheus/Grafana/Alertmanager
- Karpenter Controller
- CoreDNS 및 클러스터 필수 컴포넌트

### 9.2 Karpenter GPU NodePool

대상:

- `nvidia.com/gpu`를 요청하는 Training Job

정책:

- 동적 NodePool
- 정적 `replicas` 미지정
- 학습 작업이 없으면 실제 GPU 노드 0대
- GPU Pod Pending 시 적합한 인스턴스 생성
- 기본 capacity type은 On-Demand
- Spot은 Checkpoint와 재시도 검증 후 선택적으로 사용
- GPU taint와 label 적용
- Training Pod에 toleration과 node affinity 적용
- NodePool limits로 최대 GPU 용량 제한
- 실행 중 장기 Job 보호를 위한 disruption 정책 적용

KEDA는 사용하지 않는다. Training Controller가 SQS 메시지를 소비하고 Job을 생성한다.

---

## 10. 동기·비동기 처리 경계

### 10.1 동기 처리

- Dataset CRUD
- UploadSession 생성
- Presigned URL 발급
- SINGLE_PUT 또는 Multipart Upload 완료 요청
- TrainingJob 생성
- TrainingJob 조회 및 취소 요청
- Model 및 Deployment 조회
- 추론 요청
- JSON Schema 검증

### 10.2 비동기 처리

- 파일 검증 및 Parquet 변환
- 컬럼 스키마·통계 추출
- GPU 학습
- Checkpoint 저장
- Model Artifact 저장
- KServe 배포 생성·변경
- 추론 로그 S3 적재
- Soft Delete 대상 물리 삭제
- OutboxEvent 발행

### 10.3 공통 원칙

동기 API는 장기 작업을 직접 실행하지 않고 상태 리소스를 반환한다.

실제 장기 처리는 Kubernetes Job 또는 Controller가 수행한다.

---

## 11. 주요 요청 흐름

### 11.1 DatasetVersion 업로드

이 흐름은 이미 존재하는 Dataset에 새 DatasetVersion을 추가하는 운영 흐름이다. 최초 Dataset 생성 직후 첫 파일을 업로드하는 경우에도 Dataset 생성과 DatasetVersion 업로드는 연속된 별도 단계로 처리할 수 있다.

```text
1. Client가 기존 Dataset에 새 DatasetVersion 업로드 요청
2. Backend API가 부모 Dataset 행을 잠그고 다음 version_number를 계산
3. Backend API가 DatasetVersion을 PENDING으로 생성
4. Backend API가 양수인 `expected_size_bytes`를 검증하고, `<= 16 MiB`는 SINGLE_PUT, `> 16 MiB`는 MULTIPART를 선택해 UploadSession을 생성
5. SINGLE_PUT은 단일 PUT URL을, MULTIPART는 S3 Multipart Upload와 첫 Part용 presigned URL을 발급하며 UploadSession을 INITIATED에서 UPLOADING으로 전이
6. Client가 S3에 직접 업로드
7. Client가 UploadSession 완료 API 호출
8. SINGLE_PUT은 Multipart Complete 호출 없이, MULTIPART는 `ceil(expected_size_bytes / part_size_bytes)`로 계산한 Part 수에 맞춰 중복 없는 `{1, ..., expected_part_count}` Part 번호 집합을 검증한 뒤 CompleteMultipartUpload를 수행
9. HeadObject로 객체 존재와 ContentLength를 동기 검증한다. S3 Multipart ChecksumSHA256은 composite checksum이므로 전체 파일 SHA-256과 직접 비교하지 않는다.
10. 같은 DB 트랜잭션에서 UploadSession을 COMPLETED로 변경
11. DatasetVersion의 original_storage_uri, size_bytes, checksum을 기록
12. DatasetVersion을 UPLOADED로 변경하고 OutboxEvent 기록
13. Outbox Publisher가 SQS 발행
14. Dataset Processing Controller가 Job 생성
15. Job이 S3 객체 전체를 스트리밍하여 전체 파일 SHA-256을 계산하고 expected_checksum과 비교해 최종 무결성을 검증한 뒤, CSV/XLSX 파싱·Parquet 변환·스키마 추출
16. Parquet과 DatasetColumn 결과를 S3/RDS에 저장
17. DatasetVersion을 READY 또는 FAILED로 변경
```

### 11.2 학습 요청

```text
신규 Model:
1. Client가 Model 정보, DatasetVersion, 학습 설정, Idempotency-Key를 함께 요청
2. Backend API가 DatasetVersion을 FOR SHARE로 조회
3. Dataset 소유권, Dataset 미삭제 상태, DatasetVersion READY 상태를 검증
4. Model, 최초 TrainingJob(QUEUED), OutboxEvent를 동일 트랜잭션에 기록

기존 Model 재학습:
1. Client가 기존 model_id, DatasetVersion, 학습 설정, Idempotency-Key를 요청
2. Backend API가 Model 및 DatasetVersion 소유권과 상태를 검증
3. TrainingJob(QUEUED)과 OutboxEvent를 동일 트랜잭션에 기록

공통 비동기 실행:
1. Outbox Publisher가 SQS 발행
2. Training Controller가 RDS에서 최신 TrainingJob을 재조회하고 authoritative quota를 검증
3. quota 가능 시 조건부 `QUEUED → SCHEDULING` 후 결정적 Kubernetes Job을 생성; 부족 시 QUEUED를 유지하고 메시지를 삭제해 Reconciler가 재검사
4. GPU Pod가 Pending이고 Karpenter가 GPU Node를 생성
5. Training Controller가 Pod Running을 확인해 RUNNING으로 전이하고 Training Job이 S3 데이터로 학습
6. retry Pod는 최신 유효 checkpoint를 resume하고 기존 MLflow parent Run을 재사용
7. Checkpoint를 저장하고, 로컬 artifact·ModelInterface 준비 뒤 ModelVersion CREATING과 model_version_id를 확정
8. 확정된 model_version_id로 staging·final immutable 경로에 publish하고 ModelVersion과 ModelInterface를 finalization해 READY를 publish marker로 사용
9. 모든 ModelVersion.model_id는 TrainingJob.model_id와 동일하게 생성하며 retry는 기존 후보 row를 재사용
10. Kubernetes Job Complete 뒤 Controller가 최대 10분간 결과 finalization을 기다리고 READY·CREATING·FAILED 후보를 집계
11. READY 1개 이상·CREATING 0개면 부분 성공을 포함해 SUCCEEDED, 그 외는 원인별 FAILED로 변경
12. Job 종료 후 Karpenter가 유휴 GPU Node 제거
```

SQS는 wake-up signal이며 RDS가 영속적 기준이다. 60초 Periodic Reconciler는 메시지 누락, DLQ 이동, Controller 장애, Kubernetes 상태 불일치를 RDS 기준으로 복구한다. 이는 운영 목표 설계이며 로컬 과제 구현 완료를 의미하지 않는다.

### 11.3 모델 배포

```text
1. Client가 ModelVersion, 배포 이름, environment, replica 정책을 지정
2. Backend API가 ModelVersion → Model의 소유권과 Model 미삭제 상태를 검증
3. 요청 컨텍스트의 user_id를 InferenceDeployment.user_id로 저장
4. Backend API가 InferenceDeployment를 PENDING으로 생성
5. Deployment Controller가 KServe InferenceService 생성
6. Model Serving Pod가 S3 Artifact 로드
7. readiness 확인
8. InferenceDeployment를 READY로 변경
9. DEPLOYING 오류는 FAILED로 변경하고, UPDATING 오류·timeout은 rollback을 시도해 rollback 실패·timeout일 때만 FAILED로 변경
```

`environment`는 `DEVELOPMENT`, `STAGING`, `PRODUCTION` 중 하나이며 기본값 없이 필수다. KServe Standard Mode와 scale-to-zero 제외 결정에 따라 `min_replicas`는 1 이상이다.

### 11.4 추론

```text
1. Client가 ALB를 통해 Inference Gateway 호출
2. Gateway가 인증·인가 수행
3. RDS에서 Deployment·ModelVersion·ModelInterface 조회
4. JSON Schema로 입력 검증
5. public endpoint가 아닌 cluster-local KServe ClusterIP Service 호출
6. Model Serving Pod가 추론 수행
7. Gateway가 출력 검증 및 응답 변환
8. 추론 로그를 비동기로 S3 적재
9. Athena가 내부 분석에 사용
```

---

## 12. 데이터 저장 정책

### 12.1 RDS PostgreSQL

저장 대상:

- User
- Dataset
- DatasetVersion
- DatasetColumn
- UploadSession
- TrainingJob
- TrainingJobEvent
- TrainingCheckpoint metadata
- Model
- ModelVersion
- ModelInterface
- InferenceDeployment
- AuditLog
- OutboxEvent

RDB에는 대용량 파일 본문, Model Artifact 또는 InferenceLog 원문을 저장하지 않는다.

운영 HA는 RDS Multi-AZ DB instance deployment를 사용한다. Multi-AZ DB cluster, Read Replica, RDS Proxy는 초기 baseline에 포함하지 않는다. failover 중 기존 connection이 끊어질 수 있으므로 application은 write를 fail closed하고 깨진 connection을 폐기한 뒤 RDS DNS endpoint로 재연결하며, 결과가 불확실한 transaction은 business state 재확인 후 처리한다.

### 12.2 S3

예시 prefix:

```text
s3://argmax-mini/
├── datasets/original/
├── datasets/processed/
├── checkpoints/
├── models/
├── mlflow-artifacts/
└── inference-logs/
```

정책:

- SSE-KMS 암호화
- TLS 전송
- 미완료 Multipart Upload 자동 중단
- 원본 DatasetVersion 불변성 유지
- Soft Delete 후 30일 동안 객체 보존
- Cleanup Job이 S3 삭제 성공 후 RDB 물리 삭제

### 12.3 SQS

- Dataset Processing Queue
- Training Queue
- 필요 시 DLQ
- at-least-once 전달을 전제로 Consumer 멱등성 적용

---

## 13. 멱등성 및 정합성

### 13.1 사용자 요청 멱등성

TrainingJob 생성은 다음 제약을 사용한다.

```text
UNIQUE(user_id, idempotency_key)
```

동일 사용자의 동일 키 재요청은 기존 TrainingJob을 반환한다.

### 13.2 메시지 멱등성

Consumer는 다음 식별자를 기준으로 중복 효과를 방지한다.

- event_id
- training_job_id 또는 dataset_version_id
- 조건부 상태 UPDATE
- 결정적 Kubernetes 리소스 이름

`OutboxEvent.idempotency_key`는 API 요청과 이벤트의 감사·추적 metadata이며 Consumer 멱등성 판단에는 사용하지 않는다.

Exactly-once 전달로 표현하지 않는다.

### 13.3 Kubernetes Job 중복 방지

- 결정적 Job 이름
- PostgreSQL 조건부 상태 갱신
- Kubernetes 리소스 존재 여부 확인
- Controller reconciliation

### 13.4 버전 번호 동시성

DatasetVersion과 ModelVersion의 `version_number`는 부모 리소스 내부 순번이다.

- 부모 Dataset 또는 Model 행을 `SELECT ... FOR UPDATE`로 잠근다.
- 현재 최대 version_number에 1을 더해 새 번호를 계산한다.
- `UNIQUE(parent_id, version_number)`로 최종 정합성을 보장한다.

### 13.5 TrainingJob 생성 전 교차 엔티티 검증

`DatasetVersion.status = READY`는 다른 테이블 값을 참조하므로 DB CHECK로 표현하지 않는다.

TrainingJob 생성 서비스가 하나의 트랜잭션에서 다음을 검증한다.

- DatasetVersion 존재 여부
- Dataset 및 Model 소유권
- Dataset과 Model의 Soft Delete 여부
- DatasetVersion READY 상태
- 사용자 GPU quota
- `UNIQUE(user_id, idempotency_key)`

---

## 14. GPU Quota와 우선순위

### 14.1 Quota

서비스 정책으로 다음을 제한한다.

- 사용자별 활성 TrainingJob 수
- 사용자별 동시 GPU 수
- GPU NodePool 및 platform/environment 전체 GPU capacity 상한

정확한 수치는 운영 설정값으로 관리한다.

### 14.2 PriorityClass

예시:

```text
system-critical
production-training
standard-training
```

사용자가 임의로 PriorityClass를 지정하지 않으며, 서비스 정책이 결정한다.

12~24시간 장기 학습의 중단 위험을 줄이기 위해 기본적으로 비선점 또는 제한적 선점 정책을 사용한다.

---

## 15. 보안

### 15.1 비밀정보

```text
AWS Secrets Manager
→ External Secrets Operator
→ Kubernetes Secret
→ Pod
```

대상:

- RDS 자격증명
- MLflow DB 자격증명
- Grafana 관리자 자격증명
- 외부 연동 Secret

### 15.2 AWS 권한

Pod에 장기 Access Key를 저장하지 않는다.

IRSA를 사용해 S3, SQS 접근 권한을 부여한다. Secrets Manager는 ESO만 직접 접근하며 일반 application workload는 Kubernetes Secret을 통해 받는다.

### 15.3 네트워크와 암호화

- 외부 트래픽 TLS
- AWS WAF를 ALB에 연결
- S3 SSE-KMS
- RDS 저장 암호화
- SQS 서버 측 암호화
- EBS 암호화
- 내부 MLflow UI는 외부 엔드유저에게 공개하지 않음

VPC Security Group은 Internet→ALB(443), ALB→Backend API/Inference Gateway, EKS application/node boundary→RDS(5432)의 VPC 수준 경계를 담당한다. RDS는 public inbound를 허용하지 않는다. Pod-level ingress/egress는 Amazon VPC CNI native NetworkPolicy, AWS API 권한은 IRSA가 담당하며 Security Groups for Pods는 초기 범위에서 제외한다.

### 15.4 Workload 보안 기본값

Amazon VPC CNI native NetworkPolicy를 사용하며 application namespace는 default-deny ingress/egress를 기본으로 한다. 각 workload에는 필요한 dependency만 최소 허용하고, DNS resolution을 위해 CoreDNS(`kube-dns`)로의 UDP/TCP 53 egress를 허용한다. workload별 상세 egress 정책은 [분석·보안·오류 대응 설계](analysis-security-resilience-design.md)를 따른다.

application/Job workload는 non-root, privilege escalation 금지, Linux capability `ALL` drop, `RuntimeDefault` seccomp를 기본 SecurityContext로 사용한다. privileged, hostNetwork, hostPID, hostIPC, hostPath는 금지한다.

---

## 16. 관측 및 로그

### 16.1 Prometheus/Grafana

EKS 내부에서 운영한다.

구성:

- Prometheus
- Alertmanager
- Grafana
- kube-state-metrics
- node-exporter
- NVIDIA DCGM Exporter

수집 대상:

- Backend API
- Dataset Processing Controller/Job
- Training Controller/Job
- KServe
- Karpenter
- Kubernetes Node/Pod/Job
- GPU 사용률·메모리·온도·오류

Prometheus label에는 `user_id`, `training_job_id`, `deployment_id` 등 high-cardinality UUID를 사용하지 않는다. 개별 식별자가 필요한 분석은 structured log, RDS event, Athena를 사용한다.

### 16.2 CloudWatch

- ALB
- RDS
- SQS
- S3
- EKS Control Plane
- 중앙 로그

Grafana에서 Prometheus와 CloudWatch를 함께 조회한다.

### 16.3 중앙 로그

```text
Application stdout/stderr
Kubernetes Job logs
Controller logs
KServe runtime logs
→ Fluent Bit
→ CloudWatch Logs
```

구조화 로그 필드 예시:

- timestamp
- level
- service
- request_id
- user_id
- resource_id
- training_job_id
- dataset_version_id
- error_code

`user_id`와 resource ID는 필요한 operational correlation을 위한 structured log field로 사용할 수 있다. 반면 credential, token, Secret, raw Dataset row, raw inference feature/prediction 등 민감 payload 원문은 기록하지 않는다.

### 16.4 AuditLog와 InferenceLog 구분

- AuditLog: 누가 어떤 관리 행위를 했는지 기록하는 RDB 엔티티
- InferenceLog: 추론 요청·응답 분석용 S3 데이터셋

감사 대상 business mutation이 성공하면 AuditLog SUCCESS와 같은 PostgreSQL transaction으로 commit하며, SUCCESS Audit 기록이 실패하면 mutation을 성공으로 commit하지 않는다. 거절되었거나 rollback된 요청의 AuditLog FAILURE는 별도 best-effort transaction으로 기록하고, 그 기록 실패는 원래 API/business failure 결과를 바꾸지 않는다. 이 원칙은 HTTP 요청에만 한정하지 않으며, 감사 대상으로 정의된 SYSTEM lifecycle mutation에도 적용한다. 일반 reconciliation iteration, Kubernetes GET, retry attempt, training 실행 상태 이력은 AuditLog 대신 `TrainingJobEvent`, application log, metrics로 남긴다.

---

## 17. 분석 환경

InferenceLog는 S3 Parquet 분석 데이터셋으로 저장한다. 정상 inference에서 ModelInterface input validation, serving, Gateway output validation이 모두 성공하면 metadata와 validated input/output을 모델 품질 분석용 JSON-compatible `input_payload_json`, `output_payload_json`으로 적재한다. 이는 application/structured operational log와 별개다. input validation 실패는 error/metadata만 기록하고, serving 실패 또는 invalid serving response는 validated input과 error metadata만 기록하며 output payload는 저장하지 않는다. 초기 Hive-style partition policy는 `year/month/day/hour`이다.

```text
partition key: year, month, day, hour
Parquet column: deployment_id, model_version_id, user_id, request_id, http_status, error_code,
                input_payload_json, output_payload_json
not stored: Authorization, Cookie, JWT/token, credential, Secret, presigned URL,
            internal infrastructure URI, HTTP header 원문
```

`deployment_id`, `model_version_id`, `user_id`, `request_id`, `http_status`, `error_code`는 high-cardinality partition key가 아니라 Parquet column이다.

예시 경로:

```text
s3://argmax-mini/inference-logs/
  year=2026/month=08/day=06/hour=18/
```

Glue Data Catalog가 테이블 스키마를 관리하고 Athena가 분석 쿼리를 수행한다.

RDS OLTP 쿼리와 Athena OLAP 쿼리를 분리한다.

---

## 18. CI/CD

운영 목표 흐름:

```text
GitHub
→ GitHub Actions
   ├── test/lint
   ├── container build
   ├── vulnerability scan
   └── ECR push
→ Helm values 또는 image tag 변경
→ Argo CD
→ EKS 배포
```

- GitHub Actions: 검증과 이미지 빌드
- ECR: 이미지 저장
- Helm: Kubernetes 배포 템플릿
- Argo CD: Git 기준 배포 동기화

실제 과제 구현에서는 운영 CI/CD 전체를 구축하지 않는다.

---

## 19. 로컬 평가 환경 대응

| 운영 환경 | 로컬 평가 환경 |
|---|---|
| EKS | Docker Compose |
| RDS PostgreSQL | PostgreSQL 컨테이너 |
| S3 | 메타데이터 URI 또는 선택적 MinIO |
| SQS | 단순 Worker 또는 테스트 대체 경로 |
| Kubernetes Job | Worker 프로세스 또는 단순 메타데이터 처리 |
| Secrets Manager | Compose 기본 환경 변수 |
| ALB/WAF/Route 53 | localhost 포트 |
| KServe/MLflow/Karpenter | 설계 범위, 로컬 구현 제외 |

로컬 실행은 AWS 자격증명과 수동 `.env` 생성을 요구하지 않는다.

---


## 20. Dataset API Aggregate 조회

Dataset 테이블은 논리 리소스만 저장하며 파일 메타데이터를 비정규화하지 않는다.

API 응답에서는 다음 두 개념을 구분한다.

- `latest_version`: 상태와 관계없이 `version_number`가 가장 큰 버전
- `latest_ready_version`: `READY` 상태 중 `version_number`가 가장 큰 버전

목록 API는 최신 버전의 요약 상태를 제공할 수 있고, 상세 API는 두 버전을 함께 제공할 수 있다.

```text
Dataset table
= name, description, ownership, soft delete

DatasetVersion table
= original file format, size, URI, checksum, processing status

Dataset aggregate response
= Dataset + latest_version + latest_ready_version
```

`dataset_versions.file_format`은 사용자가 업로드한 원본 형식이며 `CSV`, `XLSX`만 허용한다. 내부 Parquet 처리본은 `processed_storage_uri`로 표현한다. 지원하지 않는 업로드 형식은 API에서 `422 Unprocessable Entity`로 거부한다.

---

## 21. RDB 도메인 모델 기준

RDB 스키마의 상세 컬럼, NULL, 기본값, FK, ON DELETE, Unique, Check Constraint, Index 및 상태 집합은 `data-model-v5.md`를 단일 기준문서로 사용한다.

핵심 정책:

- 모든 PK는 UUID v4
- 모든 운영 시간은 `TIMESTAMPTZ`
- 상태는 `VARCHAR + CHECK`
- Dataset과 Model만 30일 Soft Delete 대상
- DatasetVersion 원본은 불변
- Dataset → DatasetVersion은 `ON DELETE CASCADE`
- TrainingJob이 참조하는 DatasetVersion은 `RESTRICT`로 물리 삭제 차단
- UploadSession과 DatasetColumn은 DatasetVersion 삭제 시 `CASCADE`
- TrainingJobEvent와 TrainingCheckpoint는 TrainingJob 삭제 시 `CASCADE`
- ModelVersion과 InferenceDeployment는 provenance와 배포 안전성을 위해 부모 삭제를 `RESTRICT`
- AuditLog.actor_user_id는 User FK와 `ON DELETE SET NULL`
- AuditLog.resource_id와 OutboxEvent.aggregate_id는 다형적 참조이므로 FK 없음
- OutboxEvent는 `next_attempt_at` 기반 재시도와 발행 완료 후 30일 보존 정책 적용

AuditLog에서 `actor_type='USER'`, `actor_user_id=NULL`은 원래 사용자 행위였으나 해당 User 레코드가 이후 물리 삭제된 상태를 의미한다.

---

## 22. 구현 우선순위


### P0

- Dataset CRUD
- Dataset 테이블은 논리 리소스 구조를 유지
- 상세 응답에서 DatasetVersion 정보를 aggregate 형태로 제공할 수 있으나 DB에 최신 버전 캐시 컬럼을 중복 저장하지 않음
- PostgreSQL
- Alembic
- Docker Compose
- Health Check
- 고정 평가 사용자
- 테스트
- README

### P1

- DatasetVersion 생성·조회
- 상태 및 제약조건 구현

### P2

- TrainingJob 생성·조회·취소
- Outbox metadata
- 멱등성

### 운영 설계 전용

- EKS
- KServe
- Karpenter
- MLflow
- Prometheus/Grafana
- Athena/Glue
- Secrets Manager
- GitOps

---

## 23. 최종 기술 스택

| 영역 | 기술 |
|---|---|
| API | FastAPI |
| ORM | SQLAlchemy |
| 데이터 검증 | Pydantic v2 |
| Migration | Alembic |
| 운영 Kubernetes | Amazon EKS |
| 로컬 실행 | Docker Compose |
| 상시 노드 | EKS Managed Node Group |
| GPU 노드 | Karpenter 동적 GPU NodePool |
| RDB | Amazon RDS for PostgreSQL |
| Object Storage | Amazon S3 |
| Queue | Amazon SQS |
| Container Registry | Amazon ECR |
| DNS | Route 53 |
| 외부 보호 | AWS WAF |
| L7 진입 | ALB + AWS Load Balancer Controller |
| Dataset 처리 | Controller + Kubernetes Job |
| 학습 | Training Controller + Kubernetes Job |
| 모델 서빙 | KServe Standard Mode |
| 추론 API | Inference Gateway |
| 실험 추적 | MLflow |
| 분석 | S3 + Athena + Glue Data Catalog |
| 비밀정보 | Secrets Manager + External Secrets Operator |
| Pod AWS 권한 | IRSA |
| 메트릭 | Prometheus |
| 시각화 | Grafana |
| 경보 | Alertmanager |
| GPU 메트릭 | NVIDIA DCGM Exporter |
| 중앙 로그 | Fluent Bit + CloudWatch Logs |
| AWS 관측 | CloudWatch |
| CI/CD | GitHub Actions + Helm + Argo CD |
| Redis | 초기 제외 |
| KEDA | 제외 |
| Knative | 제외 |
| Envoy Gateway | 제외 |
| CDN | 초기 제외 |
