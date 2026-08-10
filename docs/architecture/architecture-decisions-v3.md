# ArgMax Mini Architecture Decision Records

## 1. 문서 목적

이 문서는 ArgMax Mini의 시스템 및 데이터 모델 설계 과정에서 확정한 주요 아키텍처 결정을 기록한다.

각 결정은 다음을 포함한다.

- Context: 해결해야 할 문제와 제약
- Decision: 채택한 결정
- Rationale: 선택 근거
- Consequences: 예상 결과와 운영상 주의점
- Alternatives: 검토했지만 선택하지 않은 대안

상태 표기:

- `Accepted`: 확정
- `Proposed`: 추가 검토 필요
- `Superseded`: 다른 결정으로 대체

---

# ADR-001. AWS EKS를 운영 실행 환경으로 선택

- 상태: Accepted

## Context

ArgMax Mini는 API, 대용량 Dataset 처리, 12~24시간 GPU 학습, 모델 서빙 및 관측 워크로드를 운영해야 한다.

학습 작업은 API 프로세스와 생명주기를 분리해야 하고, GPU 자원 할당 및 동적 확장이 필요하다.

## Decision

운영 컨테이너 실행 환경으로 Amazon EKS를 사용한다.

로컬 평가 환경은 Docker Compose로 별도 구성한다.

## Rationale

- Kubernetes Job을 통한 장기 작업 분리
- KServe 기반 모델 서빙
- Karpenter 기반 GPU 노드 프로비저닝
- 워크로드별 resource request/limit, taint/toleration, affinity 적용
- 운영 목표 아키텍처와 로컬 평가 구현의 명확한 분리

## Consequences

- 운영 설계에는 Kubernetes Controller, Job, NodePool, Service가 포함된다.
- 과제 구현은 EKS 실제 배포가 아니라 Docker Compose 실행 환경을 제공한다.
- AWS 기능을 실제 구현 완료로 표현하지 않는다.

## Alternatives

- ECS/Fargate: 컨테이너 실행에는 적합하지만 KServe와 Kubernetes Job 중심 설계가 분리된다.
- Lambda: 장기 실행과 대용량 파일 처리에 부적합하다.

---

# ADR-002. Control Plane과 Data Plane을 분리

- 상태: Accepted

## Context

비즈니스 상태 관리, 작업 생성, 실제 데이터 처리, GPU 학습 및 추론은 서로 다른 장애·확장 특성을 가진다.

## Decision

Control Plane과 Data Plane을 논리적으로 분리한다.

Control Plane:

- Backend API
- Outbox Publisher
- Dataset Processing Controller
- Training Controller
- Deployment Controller
- Inference Gateway
- RDS PostgreSQL
- SQS

Data Plane:

- Dataset Processing Job
- Training Job
- KServe Model Serving Pod
- S3
- CPU/GPU Node

## Rationale

- API와 장기 작업 생명주기 분리
- 재시작 후 작업 지속성 확보
- 장기 작업의 장애 영향 범위 축소
- 워크로드별 독립 확장과 자원 격리

## Consequences

- Controller reconciliation 설계가 필요하다.
- 논리적 책임 분리가 곧 독립 마이크로서비스 구현을 의미하지는 않는다.
- 하나의 코드베이스를 여러 프로세스 역할로 배포할 수 있다.

---

# ADR-003. RDS PostgreSQL을 비즈니스 기준 저장소로 사용

- 상태: Accepted

## Context

Dataset, TrainingJob, Model, 삭제·복원, 배포 상태 등은 트랜잭션과 제약조건이 필요한 OLTP 데이터다.

## Decision

Amazon RDS for PostgreSQL을 비즈니스 데이터의 기준 저장소로 사용한다.

## Rationale

- FK, Unique, Partial Unique Index, Transaction 지원
- JSONB를 통한 가변 지표와 하이퍼파라미터 저장
- Transactional Outbox 구현 가능
- 서비스 도메인 상태의 일관된 기준 제공

## Consequences

- 대용량 파일 본문과 모델 artifact는 저장하지 않는다.
- InferenceLog는 RDB 일반 엔티티로 저장하지 않는다.
- Alembic을 사용해 스키마를 관리한다.

## Alternatives

- DynamoDB: 일부 메타데이터에는 가능하지만 관계·제약·트랜잭션 중심 도메인에 불리하다.
- MLflow DB를 비즈니스 기준 저장소로 사용: 서비스 소유권·삭제·복원 정책을 대체하지 못한다.

---

# ADR-004. S3 Direct Upload 적용

- 상태: Accepted

## Context

사용자는 최대 2 GB CSV 또는 Excel 파일을 업로드한다.

API 서버가 파일을 직접 중계하면 네트워크, 메모리, timeout 및 확장 부담이 커진다.

## Decision

Presigned URL을 사용해 Client가 S3에 직접 업로드하도록 한다. `expected_size_bytes <= 16 MiB`는 `SINGLE_PUT`, `expected_size_bytes > 16 MiB`는 `MULTIPART`를 사용하며, `16 MiB = 16 * 1024 * 1024 bytes`다. `expected_size_bytes`는 서비스 계층에서 양수여야 한다.

## Rationale

- API 서버의 대용량 파일 proxy 제거
- 작은 파일의 단순한 단일 PUT과 큰 파일의 Multipart 재시도·병렬 업로드를 모두 지원
- 원본 파일을 S3에 불변 객체로 저장
- DatasetVersion과 UploadSession으로 상태 추적

## Consequences

- `UploadSession.upload_method`는 SINGLE_PUT 또는 MULTIPART다. SINGLE_PUT은 `upload_id`와 `part_size_bytes`가 모두 NULL이며, MULTIPART는 둘 다 저장한다.
- MULTIPART의 예상 Part 수는 저장하지 않고 `ceil(expected_size_bytes / part_size_bytes)`로 계산한다. 완료 요청은 중복 없이 `{1, ..., expected_part_count}`와 정확히 일치하는 Part 번호 집합만 허용한다.
- 업로드 완료 API는 SINGLE_PUT에는 Multipart Complete 호출을 하지 않고, MULTIPART에는 CompleteMultipartUpload를 호출한 뒤 HeadObject로 객체 존재와 ContentLength를 동기 확인한다.
- HeadObject 검증은 전체 파일 SHA-256을 직접 비교하지 않는다. S3 Multipart ChecksumSHA256은 composite checksum이며, Dataset Processing Job이 S3 객체 전체를 스트리밍해 계산한 전체 파일 SHA-256을 클라이언트 제출 expected_checksum과 비교하여 최종 무결성을 검증한다.
- 검증 성공 시 같은 DB 트랜잭션에서 UploadSession을 COMPLETED로 변경하고 DatasetVersion의 원본 URI, 실제 크기, checksum, 상태를 UPLOADED로 갱신하며 OutboxEvent를 기록한다.
- CSV/XLSX 파싱, Parquet 변환, 스키마 추출은 이후 비동기 Dataset Processing Job이 수행한다.
- 미완료 MULTIPART Upload lifecycle 정책이 필요하다.
- 원본과 처리본 URI를 분리한다.
- 외부 원본 형식은 CSV와 XLSX만 허용하고 지원하지 않는 형식은 API에서 422로 거부한다.

## Alternatives

- API proxy upload: 최대 2 GB 요구에 부적합하다.
- RDB BLOB 저장: 대용량 파일과 OLTP 메타데이터 역할이 혼재한다.

---

# ADR-005. Dataset 처리 작업을 Controller와 Kubernetes Job으로 분리

- 상태: Accepted

## Context

CSV/Excel 처리에는 파일 검증, 압축 해제 제한, Parquet 변환, 스키마 추출 및 임시 저장 공간이 필요하다.

파일별 CPU·메모리·ephemeral-storage 사용량 차이가 크다.

## Decision

Dataset Processing Controller와 Dataset Processing Kubernetes Job을 분리한다.

Controller:

- SQS 메시지 소비
- 처리 여부 판단
- 중복 방지
- 재시도 판단
- Job 생성
- 상태 reconciliation

Job:

- 파일 다운로드와 검증
- CSV/Excel 파싱
- Parquet 변환
- 스키마·통계 추출
- 결과 S3/RDS 저장

## Rationale

- 작업별 자원 격리
- OOM과 파싱 오류의 영향 범위 축소
- timeout과 retry 정책 분리
- 작업별 로그와 상태 추적
- EKS 중심 아키텍처 일관성

## Consequences

- Kubernetes API 접근 권한이 필요하다.
- DB 상태와 Job 상태 reconciliation이 필요하다.
- retryable/non-retryable 오류 분류가 필요하다.

## Alternatives

- 상시 Worker 직접 처리: 장애와 자원 격리가 부족하다.
- Lambda: 15분 실행 제한과 임시 저장 제약으로 부적합하다.
- ECS/Fargate: 가능하지만 EKS와 이중 오케스트레이션이 된다.
- AWS Batch: 현재 과제 규모에 비해 과도하다.

---

# ADR-006. SQS와 Transactional Outbox를 사용

- 상태: Accepted

## Context

TrainingJob 또는 Dataset 처리 상태를 DB에 기록한 뒤 메시지를 발행할 때 이중 쓰기 불일치가 발생할 수 있다.

## Decision

동일 PostgreSQL 트랜잭션에서 비즈니스 엔티티와 OutboxEvent를 기록한다.

Outbox Publisher는 `published_at IS NULL AND next_attempt_at <= now()`인 이벤트를 `FOR UPDATE SKIP LOCKED`로 claim하여 SQS로 발행한다.

발행 실패 시 `retry_count`, `last_error`, `next_attempt_at`을 갱신하고 지수 백오프를 적용한다. 발행 완료 이벤트는 30일 보존 후 Cleanup Job이 배치 삭제한다.

## Rationale

- DB commit과 이벤트 생성의 원자성 확보
- SQS 기반 비동기 처리
- 복수 Publisher에서 `FOR UPDATE SKIP LOCKED` 사용 가능

## Consequences

- SQS 전달은 at-least-once로 간주한다.
- SQS 전송 성공 후 `published_at` 갱신 전 장애 시 중복 발행될 수 있다.
- Consumer는 event_id, aggregate/resource ID, 조건부 상태 UPDATE 및 결정적 Kubernetes 리소스 이름으로 멱등성을 보장한다. `OutboxEvent.idempotency_key`는 API 요청과 이벤트의 감사·추적 metadata이며 Consumer 멱등성 판단에는 사용하지 않는다.
- Exactly-once로 표현하지 않는다.
- pending 조회는 `next_attempt_at` partial index를 사용해 SQS 장애 중 hot loop를 방지한다.
- 미발행 이벤트는 자동 삭제하지 않는다.

## Alternatives

- API가 DB commit 후 직접 SQS 발행: 장애 시 메시지 누락 가능성이 있다.
- Redis Queue: SQS와 역할이 중복되고 관리 대상이 증가한다.

---

# ADR-007. TrainingJob 생성 API에 사용자 단위 Idempotency Key 적용

- 상태: Accepted

## Context

사용자가 timeout 또는 네트워크 오류로 학습 요청을 재전송하면 동일 TrainingJob이 중복 생성될 수 있다.

## Decision

TrainingJob에 `idempotency_key VARCHAR(255)`를 저장하고 다음 제약을 사용한다.

```text
UNIQUE(user_id, idempotency_key)
```

## Rationale

- 사용자 요청 재전송에 대한 중복 생성 방지
- 서로 다른 사용자가 같은 키를 사용할 수 있음
- UUID 외 임의 문자열 수용

## Consequences

- 동일 키 재요청 시 기존 TrainingJob을 반환한다.
- SQS Consumer 멱등성과 Kubernetes Job 중복 방지는 별도 계층에서 처리한다.

## Alternatives

- 전역 UNIQUE: 사용자 간 불필요한 충돌을 만든다.
- 키 미사용: 사용자 재시도에 취약하다.

---

# ADR-008. GPU 학습을 Kubernetes Job으로 실행

- 상태: Accepted

## Context

학습은 GPU를 사용하며 12~24시간 소요될 수 있다.

API 서버 재시작과 무관하게 계속 실행되어야 한다.

## Decision

학습을 API 내부 background task가 아닌 Kubernetes Job으로 실행한다.

초기 Training Algorithm Registry는 `XGBOOST_CLASSIFIER`, `XGBOOST_REGRESSOR`로 한정한다. 해당 Runtime은 `tree_method=hist`, `device=cuda` 또는 사용 중인 XGBoost 버전의 동등한 공식 GPU 설정을 강제한다. 사용자는 CPU execution이나 GPU backend를 hyperparameter로 override할 수 없다.

## Rationale

- API와 학습 생명주기 분리
- GPU resource request와 scheduling 제어
- Job retry, timeout, 상태 추적
- Checkpoint 기반 장기 작업 복구

## Consequences

- Training Controller는 결정적 Job 이름 `training-{training_job_id}`와 조건부 상태 갱신으로 중복 생성을 방지하고 reconciliation을 담당한다.
- Job은 `restartPolicy: Never`, `backoffLimit: 1`, `activeDeadlineSeconds: 90000`, `terminationGracePeriodSeconds: 1800`을 기본 운영값으로 한다. retry Pod는 같은 Kubernetes Job의 잔여 deadline을 사용한다.
- 지원 algorithm은 GPU-capable XGBoost만이며 Pod의 `nvidia.com/gpu` request=limit과 Runtime의 CUDA execution을 함께 보장한다. generic scikit-learn training은 초기 범위에서 제외한다.
- Processed Parquet는 XGBoost memory-efficient quantile input path로 읽는다. GPU external-memory training은 VRAM pressure가 실제로 확인될 때 검토하는 확장 경로이며, cuDF, cuML, RAPIDS RMM, Dask-CUDA, multi-GPU distributed XGBoost는 초기 baseline이 아니다.
- checkpoint_id는 애플리케이션이 사전 생성하는 TrainingCheckpoint.id이며 staging·final 경로, manifest와 DB PK에 공통 사용한다. final immutable S3 객체 검증 뒤 TrainingJob 잠금과 id 재조회에서 row가 없을 때만 sequence를 할당해 TrainingCheckpoint를 생성하고, 이 row를 resume publish marker로 사용한다. INSERT 충돌은 rollback·재조회로 멱등 처리하며 동일 ID의 metadata가 다르면 `CHECKPOINT_ID_CONFLICT`로 처리한다. sequence_number는 DB 내부 정렬 순번이며 S3 경로에 사용하지 않는다.
- Training Job은 artifact와 결과 metadata를 기록하고, Training Controller는 Kubernetes 상태를 관찰하여 TrainingJob 상태를 최종 전이한다. Kubernetes Job Complete는 비즈니스 성공과 같지 않으며, Controller가 최대 10분간 결과 finalization을 기다린 뒤 READY ModelVersion·ModelInterface·artifact 불변조건과 후보 집계를 검증해 SUCCEEDED 또는 `ALL_MODEL_CANDIDATES_FAILED`, `NO_MODEL_CANDIDATE_PRODUCED`, `TRAINING_RESULT_INCOMPLETE` FAILED를 결정한다.
- 상태 전이는 외부 사용자 PATCH API로 임의 변경하지 않는다.
- 취소 요청은 `QUEUED`, `SCHEDULING`, `RUNNING`에서 허용한다.
- `SCHEDULING` 중 취소 시 Job 생성을 중단하거나 생성 직후 Kubernetes Job terminal 상태를 확인한 뒤, terminal이 아니면 삭제한다.

## Alternatives

- FastAPI 내부 background task: 재시작·배포 시 작업 지속성을 보장하지 못한다.
- 단일 상시 학습 Worker: Job별 자원 격리와 GPU scheduling이 불리하다.

---

# ADR-009. 상시 워크로드는 Managed Node Group, GPU 학습은 Karpenter 사용

- 상태: Accepted

## Context

상시 API와 Controller는 안정적으로 유지해야 하지만 GPU 학습 수요는 간헐적이고 비용이 높다.

## Decision

- 상시 시스템 워크로드: EKS Managed Node Group
- GPU Training Job: Karpenter 동적 GPU NodePool

## Rationale

Managed Node Group:

- 상시 컴포넌트의 안정적 용량 제공
- Karpenter Controller와 CoreDNS 실행 기반 확보

Karpenter:

- Pending GPU Pod의 CPU·메모리·GPU 요구에 따라 인스턴스 선택
- 학습이 없을 때 GPU 노드 0대
- 다양한 GPU 인스턴스와 AZ 후보 활용
- Job 종료 후 유휴 노드 제거

## Consequences

- GPU NodePool은 정적 `replicas`를 지정하지 않는다.
- 기본 capacity type은 On-Demand다.
- Spot은 Checkpoint·재시도 검증 후 선택적으로 사용한다.
- disruption 및 consolidation 정책으로 장기 학습을 보호한다.
- NodePool limits로 최대 GPU 비용을 제한한다.
- KEDA는 사용하지 않는다.

## Alternatives

- GPU Managed Node Group + Cluster Autoscaler: 단순하지만 인스턴스 유형 유연성이 낮다.
- 모든 노드를 Karpenter로 운영: Karpenter Controller 자체를 실행할 기반 노드가 필요하고 상시 워크로드 안정성이 낮아질 수 있다.

---

# ADR-010. 사용자·플랫폼 GPU Quota와 PriorityClass 적용

- 상태: Accepted

## Context

NodePool 전체 상한만으로는 사용자 간 공정성과 우선순위를 제어할 수 없다.

## Decision

- 사용자별 활성 TrainingJob 수 제한
- 사용자별 동시 GPU 수 제한
- GPU NodePool과 platform/environment 전체 GPU capacity 상한
- Kubernetes PriorityClass 적용
- 기본 비선점 또는 제한적 선점

## Rationale

- 특정 사용자의 GPU 독점 방지
- 플랫폼 비용 상한과 사용자 정책 분리
- 중요 작업과 일반 작업의 우선순위 표현
- 장기 학습의 불필요한 중단 최소화

## Consequences

- API의 quota 검증은 best-effort이며, Training Controller가 scheduling 직전에 authoritative 재검증한다.
- quota 부족은 `QUEUED` 상태의 정상 대기다. Kubernetes Job을 생성하지 않고 SQS 메시지를 삭제한 뒤 Reconciler가 재검사하며, 별도 WAITING_FOR_QUOTA 상태는 초기 범위에서 사용하지 않는다.
- `QUOTA_WAITING` 이벤트는 관측용이며 최근 이벤트 기준 최소 15분 간격으로 기록한다.
- 정확한 quota 수치는 운영 설정값으로 관리한다.
- 사용자가 임의의 PriorityClass를 지정하지 못한다.

---

# ADR-011. MLflow를 내부 실험 추적 플랫폼으로 사용

- 상태: Accepted

## Context

ModelVersion의 최종 metrics_json만으로는 epoch별 metric history, 학습 환경, 파라미터 및 artifact lineage를 충분히 추적하기 어렵다.

## Decision

MLflow를 내부 실험 추적 플랫폼으로 도입한다.

MLflow는 다음을 기록한다.

- 학습 Run
- 하이퍼파라미터
- metric history
- 학습 환경
- artifact lineage

ArgMax Mini의 Model, ModelVersion, TrainingJob 및 InferenceDeployment는 RDS를 기준 저장소로 유지한다.

대용량 artifact는 S3에 저장한다.

## Rationale

- ML Engineer의 실험 비교와 재현성 지원
- 서비스 비즈니스 엔티티와 실험 추적 책임 분리
- MLflow Model Registry에 사용자 서비스 정책을 종속시키지 않음

## Consequences

- MLflow는 엔드유저에게 직접 노출하지 않는다.
- MLflow는 EKS Private Application Subnet의 private workload이며 public ALB target이 아니다. ML Engineer 접근에는 End User ingress와 분리된 authorized trusted internal/administrative network path가 필요하다.
- Client VPN, corporate/private network 등 구체 connectivity 방식은 운영 조직의 관리망 요구에 따른 integration concern으로 남기며, 현재 baseline에서 VPN, Direct Connect, bastion을 채택하지 않는다.
- MLflow 장애가 모델 관리와 추론 경로의 가용성에 직접 영향을 주지 않도록 비필수 의존성으로 구성한다.
- RDS 내 MLflow metadata는 별도 database 또는 schema로 분리한다.

## Alternatives

- MLflow 제외: 구조는 단순하지만 실험 이력과 metric history 관리가 약하다.
- MLflow를 모델 기준 저장소로 사용: Soft Delete, 복원, 소유권, Deployment 정책을 대체하지 못한다.

---

# ADR-012. Inference Gateway와 KServe의 책임을 분리

- 상태: Accepted

## Context

모델마다 입출력 구조가 다르고, 서비스 수준 인증·인가·삭제 상태 확인·로그 문맥이 필요하다.

KServe는 모델 런타임과 Kubernetes 실행을 담당하지만 ArgMax Mini의 비즈니스 정책을 알지 못한다.

## Decision

외부 추론 API와 모델 실행 계층을 Inference Gateway와 KServe로 분리한다.

Inference Gateway:

- 인증·인가
- InferenceDeployment 조회
- Model 삭제 상태 확인
- ModelInterface JSON Schema 검증
- 외부 요청과 KServe 프로토콜 변환
- 공통 timeout·오류 처리
- 추론 로그 문맥 생성

KServe:

- Model Artifact 로딩
- Serving Runtime 관리
- health/readiness
- replica/autoscaling
- rollout과 트래픽 전환
- 실제 추론 실행

## Rationale

- 서비스 경계와 모델 실행 경계 분리
- KServe 내부 리소스 외부 노출 방지
- 모델별 런타임 차이를 Gateway에서 제거
- 삭제·권한 정책을 RDS 기준으로 적용

## Consequences

- 요청 경로에 Inference Gateway가 추가되므로 일부 지연이 발생한다.
- Gateway는 stateless하게 구성하고 connection pool을 사용한다.
- Inference Gateway가 유일한 external inference application boundary이며, Gateway가 KServe의 cluster-local ClusterIP Service를 직접 호출한다.
- KServe InferenceService는 별도 public inference endpoint를 제공하지 않는다.
- 별도 KServe 외부 L7 Gateway는 데이터 경로에 추가하지 않는다.
- 장기 스트리밍·LLM 추론은 현재 범위에서 제외한다.

## Alternatives

- KServe 직접 외부 노출: 서비스 인증·인가·삭제 정책 적용이 어렵다.
- Gateway가 모델 직접 실행: 모델 런타임과 API가 결합된다.
- Knative + 별도 Gateway: scale-to-zero 요구가 없고 과제 규모에 비해 복잡하다.

---

# ADR-013. KServe Standard Mode 사용

- 상태: Accepted

## Context

현재 시나리오는 동기식 tabular model inference이며 장기 스트리밍과 scale-to-zero 요구가 명시되지 않았다.

## Decision

KServe Standard Mode를 사용한다.

## Rationale

- 표준 Kubernetes Deployment/Service 기반
- Knative 의존성 제거
- cold start 회피
- 운영 복잡도 감소
- 현재 추론 요구에 충분함

## Consequences

- 기본적으로 Knative scale-to-zero를 사용하지 않는다.
- 활성 InferenceDeployment의 `min_replicas`는 1 이상으로 제한한다.
- 모델별 autoscaling은 KServe와 Kubernetes 기능으로 구성한다.
- `DEPLOYING`의 생성·복구 실패 또는 timeout은 `FAILED`로 종결한다.
- `UPDATING`의 apply 실패 또는 timeout은 즉시 `FAILED`로 전이하지 않고 last applied configuration으로 rollback을 시도한다.
- rollback이 성공하면 이전 applied configuration의 `READY`로 복귀하며, rollback 자체의 실패 또는 timeout일 때만 `FAILED`로 전이한다.
- 향후 요청량 변동과 비용 요구가 커지면 Knative Mode를 재검토한다.

## Alternatives

- KServe Knative Mode: scale-to-zero와 revision 기능은 강하지만 현재 요구에 비해 과도하다.
- Custom Serving Deployment: KServe가 제공하는 표준화와 운영 기능을 직접 구현해야 한다.

---

# ADR-014. Redis를 초기 아키텍처에서 제외

- 상태: Accepted

## Context

Redis는 InferenceDeployment routing과 ModelInterface 조회 캐시에 사용할 수 있지만 현재 추론 처리량·지연 목표·RDS 병목이 정의되지 않았다.

## Decision

Redis와 ElastiCache를 초기 아키텍처의 필수 구성에서 제외한다.

## Rationale

- 성능 효과가 입증되지 않음
- TTL, 무효화, stale cache, fallback 설계가 추가됨
- RDS가 기준 저장소인 단순한 구조 유지
- PK/FK 인덱스와 connection pool로 초기 요구 대응 가능

## Consequences

- Inference Gateway는 RDS에서 메타데이터를 직접 조회한다.
- 필요 시 짧은 TTL의 Pod local cache를 우선 검토한다.
- 부하 테스트에서 RDS 병목이 확인되면 Redis cache-aside를 도입한다.
- Redis를 작업 큐나 분산락으로 사용하지 않는다.

## Alternatives

- ElastiCache Redis 선도입: 현재 근거 대비 운영 복잡성이 크다.
- Redis 기반 분산락: PostgreSQL 조건부 갱신과 reconciliation으로 대체 가능하다.

---

# ADR-015. Prometheus와 Grafana를 EKS 내부에서 운영

- 상태: Accepted

## Context

Dataset Job, Training Job, KServe, Karpenter 및 GPU에 대한 사용자 정의 메트릭과 대시보드가 필요하다.

## Decision

Prometheus, Alertmanager 및 Grafana를 EKS 내부 워크로드로 운영한다.

구성:

- Prometheus
- Alertmanager
- Grafana
- kube-state-metrics
- node-exporter
- NVIDIA DCGM Exporter

## Rationale

- ServiceMonitor/PodMonitor 자유 구성
- custom metric, recording rule, alert rule 확장성
- GPU와 Job 중심 관측 구성
- 과제에서 관측 설계 역량을 명확히 표현

## Consequences

- Prometheus 저장·보존·HA 운영 책임이 발생한다.
- ALB, RDS, SQS, S3 및 EKS Control Plane은 CloudWatch에서 관측한다.
- Grafana에 Prometheus와 CloudWatch를 함께 연결한다.
- 메트릭 규모와 보존 요구가 증가하면 AMP remote_write 또는 이전을 검토한다.

## Alternatives

- Amazon Managed Service for Prometheus/Grafana: 운영 확장성은 높지만 현재 규모에서는 관리형 이점보다 구성 복잡성과 비용이 크다.

---

# ADR-016. S3와 Athena로 OLAP 분석 환경 구성

- 상태: Accepted

## Context

내부 사용자는 대용량 Dataset과 추론 요청·응답을 분석한다.

분석 쿼리가 RDS OLTP에 영향을 주어서는 안 된다.

## Decision

- Dataset 처리본: S3 Parquet
- InferenceLog: S3 Parquet
- InferenceLog 초기 Hive-style partition: `year/month/day/hour`
- Schema Catalog: AWS Glue Data Catalog
- Query Engine: Amazon Athena

## Rationale

- RDS OLTP와 분석 워크로드 분리
- Parquet 기반 columnar query
- 서버 운영 없이 분석 쿼리 수행
- S3 로그와 직접 통합

## Consequences

- InferenceLog를 RDB ERD에 포함하지 않는다.
- `deployment_id`, `model_version_id`, `user_id`, `request_id`, `http_status`, `error_code`는 partition key가 아닌 Parquet column으로 저장해 high-cardinality partition explosion을 피한다.
- 정상 inference는 ModelInterface input validation, serving, Gateway output validation이 모두 성공한 경우 metadata와 validated `input_payload_json`, `output_payload_json`을 모델 품질 분석용 InferenceLog에 저장한다.
- 이는 operational log와 분리된다. Authorization, Cookie, JWT/token, credential, Secret, presigned URL, internal infrastructure URI, HTTP header 원문은 저장하지 않는다.
- durable delivery, retention, sampling, field-level masking, 개인정보 분류와 DSAR 정책은 아직 확정하지 않는다.

## Alternatives

- Trino on EKS: 유연하지만 클러스터 운영 복잡도가 증가한다.
- RDS 분석: OLTP 성능에 영향을 줄 수 있다.

---

# ADR-017. AWS Secrets Manager와 External Secrets Operator 사용

- 상태: Accepted

## Context

RDS, MLflow, Grafana 및 외부 연동 자격증명을 안전하게 전달해야 한다.

## Decision

AWS Secrets Manager에 비밀정보를 저장하고 External Secrets Operator로 Kubernetes Secret을 동기화한다.

Pod의 AWS 서비스 접근은 IRSA를 사용한다. EKS Pod Identity는 공식 지원 대안이지만 초기안에는 도입하지 않는다.

## Rationale

- 장기 AWS Access Key 제거
- Secret 중앙 관리와 회전 가능
- Kubernetes manifest에 평문 Secret 저장 방지

## Consequences

- External Secrets Operator 운영이 필요하다.
- Secret 접근 IAM 정책을 최소 권한으로 구성해야 한다.
- 로컬 평가 환경은 AWS 자격증명을 요구하지 않는 기본 설정을 사용한다.

## Alternatives

- Kubernetes Secret 직접 관리: Git 또는 배포 과정의 노출 위험이 있다.
- Access Key 환경 변수: 장기 자격증명 관리 위험이 크다.

---

# ADR-018. 중앙 로그는 Fluent Bit과 CloudWatch Logs 사용

- 상태: Accepted

## Context

API, Controller, Kubernetes Job 및 KServe 로그를 중앙에서 검색해야 한다.

## Decision

Pod stdout/stderr 로그를 Fluent Bit으로 수집하여 CloudWatch Logs에 저장한다.

## Rationale

- AWS 서비스 로그와 통합
- Job 종료 후에도 로그 보존
- request_id, training_job_id 등 구조화 로그 검색 가능

## Consequences

- 로그 포맷 표준화가 필요하다.
- 민감정보를 로그에 기록하지 않아야 한다.
- 로그 보존 기간과 비용 정책이 필요하다.

## Alternatives

- EKS 내부 Loki: 기능은 적합하지만 자체 운영 컴포넌트가 추가된다.
- Pod 로컬 로그만 사용: Job 종료 후 분석이 어렵다.

---

# ADR-019. AuditLog와 InferenceLog를 분리

- 상태: Accepted

## Context

관리 행위 감사와 추론 분석 데이터는 목적, 접근 권한 및 저장 특성이 다르다.

## Decision

- AuditLog: RDS 엔티티
- InferenceLog: S3 분석 데이터셋

AuditLog 대상:

- Dataset 생성·수정·삭제·복원
- Model 삭제·복원
- TrainingJob 생성·취소
- Deployment 생성·변경·삭제
- 영구 삭제 결과
- 권한 관련 관리 행위

## Rationale

- 감사 추적은 트랜잭션과 검색 가능한 메타데이터 필요
- 추론 로그는 대용량이며 OLAP 분석 대상
- 서로 다른 보존·접근 정책 적용

## Consequences

- HTTP inference 요청에서 생성된 InferenceLog는 해당 `request_id`로 연계한다. 정상 inference에서는 validated input/output analytical payload를 저장하며, input validation 실패에는 error/metadata만, serving 실패 또는 invalid serving response에는 validated input과 error metadata만 저장한다. 모든 AuditLog와 InferenceLog가 공통 request_id를 가져야 하는 것은 아니다.
- 비동기 workflow의 연계 기준은 `event_id + aggregate/resource ID`이며, 별도 `correlation_id`는 초기 도입하지 않는다.
- InferenceLog는 operational log와 분리되며 token, credential, Secret, Authorization/Cookie, presigned URL, internal URI, HTTP header 원문은 저장하지 않는다. durable delivery와 privacy policy는 미해결이다.

---

# ADR-020. Route 53, WAF, ALB를 외부 진입 계층으로 사용

- 상태: Accepted

## Context

Backend API와 Inference Gateway를 외부에 안전하게 노출해야 한다.

## Decision

```text
Client
→ Route 53
→ AWS WAF
→ ALB
→ Kubernetes Service
→ Pod
```

AWS Load Balancer Controller가 Kubernetes 리소스를 감시하여 ALB를 구성한다.

## Rationale

- AWS 네이티브 DNS와 L7 load balancing
- WAF 기반 기본 웹 공격 및 rate-based rule 적용
- 별도 Ingress Controller 운영 제거

## Consequences

- Ingress 리소스는 선언 객체이며 별도 네트워크 홉으로 표현하지 않는다.
- 사용자별 quota는 WAF가 아닌 애플리케이션 정책으로 처리한다.
- CloudFront는 초기 범위에서 제외한다.

## Alternatives

- Envoy Gateway 추가: 현재 요구에 비해 L7 홉과 운영 복잡성이 증가한다.
- CloudFront: 정적 웹 자산 또는 다운로드 가속 요구가 없으므로 초기 제외한다.

---

# ADR-021. GitHub Actions, Helm, Argo CD 기반 CI/CD 설계

- 상태: Accepted

## Context

운영 환경에서 이미지 빌드와 Kubernetes 배포를 일관되게 관리해야 한다.

## Decision

```text
GitHub
→ GitHub Actions
→ ECR
→ Helm manifest/value 변경
→ Argo CD
→ EKS
```

## Rationale

- CI와 CD 책임 분리
- Git 기반 선언 상태 유지
- 이미지 build/test/scan 자동화
- Kubernetes 배포 표준화

## Consequences

- 실제 과제 구현 범위에서는 전체 파이프라인을 구축하지 않는다.
- 운영 설계 요소로만 문서화한다.

## Alternatives

- GitHub Actions 직접 kubectl 배포: 단순하지만 GitOps 상태 추적이 약하다.
- 완전 수동 배포: 재현성과 감사 가능성이 낮다.

---

# ADR-022. 초기 구현은 모듈러 모놀리스로 유지

- 상태: Accepted

## Context

설계에는 여러 Controller와 Gateway 역할이 존재하지만 48시간 과제에서 각각 독립 마이크로서비스로 구현하면 범위가 과도해진다.

## Decision

초기 코드는 하나의 Backend 코드베이스를 사용하고 도메인·응용·인프라 모듈로 책임을 분리한다.

운영 시 필요한 역할만 별도 프로세스 또는 Deployment로 실행할 수 있도록 한다.

예:

```text
backend/
├── dataset/
├── training/
├── model/
├── deployment/
├── outbox/
└── shared/
```

## Rationale

- 과도한 MSA 방지
- 공통 도메인 모델과 트랜잭션 관리 용이
- 48시간 구현 범위에 적합
- 향후 프로세스 단위 분리 가능

## Consequences

- 논리적 컴포넌트와 물리적 배포 단위를 문서에서 구분한다.
- 운영 목표 구성요소를 모두 구현 완료로 표현하지 않는다.

---

# ADR-023. 로컬 평가 환경은 Docker Compose로 단순화

- 상태: Accepted

## Context

평가자는 AWS 계정과 자격증명 없이 저장소 루트에서 서버를 실행해야 한다.

## Decision

로컬 구현은 다음 명령으로 실행한다.

```bash
docker compose up -d
```

필수 구성:

- API 서비스
- PostgreSQL
- 자동 Alembic migration 또는 bootstrap
- 고정 평가 사용자
- Health Check

## Rationale

- 평가 재현성
- AWS 의존성 제거
- 구현 범위와 운영 설계의 분리

## Consequences

- KServe, Karpenter, MLflow, Athena 등은 로컬 필수 실행 대상이 아니다.
- 로컬 API와 운영 업로드 API를 동일한 것으로 표현하지 않는다.
- 수동 `.env` 생성과 AWS 자격증명을 요구하지 않는다.

---

# ADR-024. Redis, KEDA, Knative, Envoy Gateway 및 CDN 초기 제외

- 상태: Accepted

## Context

기술적으로 사용할 수 있으나 현재 요구사항과 병목 근거가 부족한 구성요소가 있다.

## Decision

다음 구성요소를 초기 기본 아키텍처에서 제외한다.

- Redis/ElastiCache
- KEDA
- Knative
- Envoy Gateway
- CloudFront CDN

## Rationale

- Redis: RDS 조회 병목이 입증되지 않음
- KEDA: Training Controller가 SQS 소비와 Job 생성을 담당
- Knative: scale-to-zero와 장기 스트리밍 요구가 없음
- Envoy Gateway: ALB + Inference Gateway + ClusterIP 경로로 충분
- CDN: 정적 자산과 캐시 가능한 응답 요구가 없음

## Consequences

다음 조건이 확인되면 재검토한다.

- Redis: RDS 메타데이터 조회가 실측 병목
- KEDA: 단순 queue depth 기반 대규모 ScaledJob 필요
- Knative: 모델별 scale-to-zero와 revision 요구 증가
- Envoy Gateway: 고급 Gateway API routing 필요
- CloudFront: 정적 프론트엔드 또는 글로벌 다운로드 가속 필요

---


# ADR-025. 논리 Model을 학습 결과보다 먼저 생성

- 상태: Accepted

## Context

최초 모델 학습 시에는 아직 ModelVersion이 존재하지 않는다. TrainingJob이 반드시 대상 Model을 참조하도록 설계하면 신규 모델 생성 흐름을 별도로 정의해야 한다.

## Decision

Model을 여러 TrainingJob과 ModelVersion을 묶는 논리 리소스로 정의한다.

신규 모델 생성 요청은 하나의 PostgreSQL 트랜잭션에서 다음을 수행한다.

1. Model 생성
2. 최초 TrainingJob 생성
3. OutboxEvent 생성
4. COMMIT

기존 Model의 재학습은 해당 `model_id`를 지정해 새 TrainingJob을 생성한다.

하나의 TrainingJob은 0개 이상의 ModelVersion을 생성할 수 있으며, 생성된 모든 ModelVersion의 `model_id`는 TrainingJob의 `model_id`와 같아야 한다.

## Rationale

- 최초 학습 전에도 대상 Model을 명확히 식별
- 신규 생성과 재학습 흐름 일관성
- 모델별 학습 이력과 버전 계보 추적
- 학습 실패 시에도 요청과 실패 이력 보존

## Consequences

- Model 자체에는 TRAINING 또는 READY 같은 단일 상태를 두지 않는다.
- 학습 상태는 TrainingJob, artifact 상태는 ModelVersion, 배포 상태는 InferenceDeployment가 각각 관리한다.
- ModelVersion 생성 시 `model_id`를 요청에서 받지 않고 TrainingJob에서 복사한다.
- Model 단위 default version과 promotion workflow는 초기 범위에서 제외한다.

## Alternatives

- 학습 성공 후 Model 생성: 실패한 최초 학습의 대상 모델 의도가 사라진다.
- Model과 TrainingJob을 별도 요청으로만 생성: 중간 실패로 빈 Model이 남을 수 있다.

---

# ADR-026. RDB 버전·소유권·삭제 정책 확정

- 상태: Accepted

## Context

DatasetVersion과 ModelVersion의 순번 생성, 사용자별 활성 이름, 배포 소유권, Soft Delete 후 물리 삭제를 DB 제약과 서비스 검증으로 일관되게 관리해야 한다.

## Decision

- DatasetVersion과 ModelVersion 순번은 부모 행을 `FOR UPDATE`로 잠근 뒤 계산한다.
- `UNIQUE(dataset_id, version_number)`와 `UNIQUE(model_id, version_number)`를 최종 방어선으로 둔다.
- Dataset과 Model 활성 이름은 사용자 단위 대소문자 무관 partial unique index로 보장한다.
- TrainingJob 멱등성은 `UNIQUE(user_id, idempotency_key)`로 보장한다.
- InferenceDeployment는 직접 `user_id`와 필수 `environment`를 저장한다.
- InferenceDeployment 생성 시 `user_id = ModelVersion.Model.user_id`를 서비스 계층에서 검증한다.
- Dataset → DatasetVersion은 `ON DELETE CASCADE`를 사용한다.
- TrainingJob이 참조하는 DatasetVersion은 `ON DELETE RESTRICT`로 삭제를 차단한다.
- AuditLog.actor_user_id는 User FK와 `ON DELETE SET NULL`을 적용하고, 다형적 resource_id에는 FK를 두지 않는다.

## Rationale

- 버전 번호 동시 생성 race condition 방지
- 소유권 조회와 배포 이름 유일성 단순화
- 종속 metadata의 안전한 Cleanup
- 학습 provenance와 감사 기록 보존

## Consequences

- 학습 이력이 없는 Dataset만 복원 기간 종료 후 전체 metadata를 물리 삭제할 수 있다.
- `actor_type='USER'`, `actor_user_id=NULL`은 해당 사용자가 이후 물리 삭제된 과거 행위를 의미한다.
- DatasetColumn 이름은 동일 버전 내 대소문자 무관 unique로 관리한다.
- Dataset API는 최신 버전 metadata를 테이블에 비정규화하지 않고 aggregate 응답으로 조합한다.

---

# ADR-027. Dataset aggregate의 최신 버전 의미 분리

- 상태: Accepted

## Context

가장 최근 생성된 DatasetVersion과 현재 학습에 사용할 수 있는 최신 READY 버전은 서로 다를 수 있다.

## Decision

Dataset API에서 다음 두 개념을 분리한다.

- `latest_version`: 상태와 관계없이 가장 큰 version_number
- `latest_ready_version`: READY 상태 중 가장 큰 version_number

Dataset 테이블에는 status, storage_uri, file_format, size_bytes, schema_json 같은 최신 버전 캐시를 저장하지 않는다.

## Rationale

- 업로드·처리 진행 상태와 학습 가능 상태를 동시에 정확히 표현
- Dataset과 DatasetVersion의 책임 분리 유지
- 비정규화 캐시 동기화 문제 방지

## Consequences

- 목록 응답은 latest_version 요약을 제공할 수 있다.
- 상세 응답은 latest_version과 latest_ready_version을 함께 제공할 수 있다.
- 필요한 조회는 LATERAL JOIN 또는 별도 쿼리로 수행한다.

---

# ADR-028. SQS를 wake-up signal로 사용하고 RDS와 Reconciler를 복구 기준으로 사용

- 상태: Accepted

## Context

SQS는 at-least-once 전달이며 메시지가 누락·지연·DLQ 이동될 수 있다. Controller 장애 중에도 TrainingJob 실행 의도가 보존되어야 하고, 메시지 존재 여부와 비즈니스 상태는 분리되어야 한다.

## Decision

SQS는 빠른 작업 시작을 위한 wake-up signal로 사용한다. RDS의 TrainingJob은 영속적 작업 레코드와 비즈니스 상태의 기준이며, Periodic Reconciler는 메시지 누락·DLQ 이동·Controller 장애·Kubernetes 상태 불일치를 복구하는 최종 안전망이다.

Reconciler는 기본 60초 주기로 상태별 최대 100건의 `QUEUED`, `SCHEDULING`, `RUNNING`, `CANCEL_REQUESTED`를 검사한다.

## Rationale

- 메시지 손실이나 DLQ 이동 뒤에도 RDS 상태를 기준으로 작업을 복구할 수 있다.
- Controller 재시작 뒤 Kubernetes와 RDS 상태를 수렴시킬 수 있다.
- SQS를 비즈니스 기준 저장소로 오해하지 않는다.

## Consequences

- SQS 메시지 없이도 Reconciler가 작업 복구를 시도할 수 있다.
- DLQ는 조사·격리 수단이며 유일한 재처리 경로가 아니다.
- Reconciler 장애 동안 처리 지연은 생길 수 있지만 작업 의도는 유실되지 않는다.
- Kubernetes와 RDS 상태 reconciliation이 필요하다.

## Alternatives

- SQS 메시지만 작업 기준으로 사용
- DLQ redrive만 복구 수단으로 사용
- 별도 workflow engine 도입

---

# ADR-029. Model artifact를 S3 검증 뒤 ModelVersion READY로 publish

- 상태: Accepted

## Context

S3와 PostgreSQL은 하나의 ACID 트랜잭션으로 묶을 수 없다. artifact 객체의 존재만으로는 사용자에게 안전한 결과인지 알 수 없고, Pod retry와 Controller 재시작 뒤에도 같은 후보 publish를 멱등적으로 이어야 한다. READY 시점에는 artifact metadata와 ModelInterface 계약도 함께 보장되어야 한다.

## Decision

- artifact를 staging과 final immutable prefix로 분리하고 final 경로에는 `model_version_id`를 사용한다.
- S3 final artifact·manifest·checksum 검증 뒤 RDB finalization을 수행한다.
- `ModelVersion.status=READY`와 정확히 하나의 ModelInterface 존재를 publish marker로 사용한다.
- candidate는 `(training_job_id, candidate_number)`로 식별하고 Pod retry는 기존 `model_version_id`를 재사용한다.
- `model_version_id`와 CREATING row는 staging 업로드 전에 확정한다.
- ModelVersion 생성 전 로컬 직렬화·ModelInterface 검증 오류는 row 없이 `CANDIDATE_TRAINING_FAILED`로 기록하고, CREATING 생성 후 publish 오류만 ModelVersion FAILED로 기록한다.
- 동일 candidate의 최초 INSERT 충돌은 rollback·재조회 뒤 기존 row의 ID·version_number·경로를 재사용한다.
- 생성 전 실패 후보는 `CANDIDATE_TRAINING_FAILED`의 distinct candidate_number로 최종 결과 집계에 포함한다. ModelVersion row가 있는 candidate는 이벤트와 이중 집계하지 않는다. `ALL_MODEL_CANDIDATES_FAILED`는 생성 전·후 실패를 모두 포함하고, `NO_MODEL_CANDIDATE_PRODUCED`는 후보 결과와 실패 이벤트가 모두 없는 경우로 제한한다.
- finalization은 조건부 UPDATE와 기존 정보 비교로 멱등 처리한다.
- Kubernetes Job Complete 뒤 최대 10분간 후보 finalization을 기다린다. READY 1개 이상·CREATING 0개이면 부분 성공을 허용한다.
- 실행 중 publish는 Training Job이, Job 종료 후 고아 CREATING reconciliation과 30분 timeout은 Training Controller/Reconciler가 처리한다.
- 10분 결과 확정 timeout 뒤 TrainingJob은 `TRAINING_RESULT_INCOMPLETE`, 잔존 CREATING ModelVersion은 `TRAINING_RESULT_FINALIZATION_TIMEOUT`으로 FAILED 처리하며 이후 READY 전이를 금지한다.
- CANCEL_REQUESTED에서는 Kubernetes Job terminal 상태를 삭제보다 먼저 확인한다. Complete면 결과 확정 절차를 적용하고, Complete 없이 삭제·종료되면 잔존 CREATING을 `MODEL_PUBLISH_CANCELLED`로 정리한 뒤 CANCELLED로 전이한다.

## Rationale

- S3 객체만 존재하는 미완료 결과가 사용자나 배포에 노출되는 것을 막는다.
- retry와 reconciliation이 동일 row와 경로를 사용해 중복 publish를 방지한다.
- 일부 후보 실패가 전체 학습 실패로 과도하게 전파되지 않는다.

## Consequences

- CREATING reconciliation과 orphan artifact cleanup이 필요하다.
- 10분 TrainingJob 결과 확정 timeout과 30분 ModelVersion CREATING timeout은 목적이 다르다. 전자는 TrainingJob 종결 및 잔존 후보 즉시 정리, 후자는 고아 publish의 최종 안전망이다.
- FAILED ModelVersion도 공개 버전 번호를 소비할 수 있어 gap을 허용한다.
- 별도 ModelVersionEvent 테이블 없이 TrainingJob 실행 이벤트를 사용한다.
- checksum은 초기에는 S3 manifest를 기준으로 하며 DB checksum 컬럼은 추가하지 않는다.

## Alternatives

- S3 업로드 전에 READY row 생성
- artifact 존재만으로 사용 가능 상태 결정
- 모든 후보 성공을 TrainingJob 성공 조건으로 강제
- 별도 ModelVersionEvent 테이블 추가
- checksum을 즉시 ModelVersion DB 컬럼으로 추가

---

# ADR-030. ArgMax Tabular Custom ServingRuntime과 immutable ModelVersion deployment 계약

- 상태: Accepted

## Context

Serving 계약과 deployment 운영 상태를 ModelVersion publish와 분리하면서도, 사용자 추론에는 검증 가능한 단일 runtime·routing 기준이 필요하다.

## Decision

ModelInterface는 per-instance/per-prediction Draft 2020-12 schema로, artifact bundle은 XGBoost `model.json`, 선언형 preprocessing과 classifier의 optional labels.json으로 제공한다. 초기 Training Algorithm Registry는 XGBoost classifier/regressor만 허용하고, KServe Standard Mode의 `argmax-tabular-runtime-v1`은 해당 `model.json`을 CPU에서 실행한다. generic scikit-learn/joblib artifact와 runtime은 future extension이다. InferenceDeployment는 immutable model_version_id와 desired/applied replica 상태를 분리하며, 유일한 external inference application boundary인 Gateway는 namespace와 service name으로 cluster-local KServe Service를 routing한다.

## Rationale

불변 ModelVersion과 선언형 preprocessing은 재현성과 serving 안전성을 높이고 desired/applied 분리는 비동기 KServe 반영 상태를 명확히 한다.

## Consequences

Deployment Controller는 60초 reconciliation과 timeout·rollback을 관리한다. KServe는 별도 public inference endpoint를 제공하지 않으며 traffic split과 ModelVersion in-place 교체는 초기 범위에서 제외한다.

## Alternatives

KServe 기본 runtime만 사용, model_version in-place 교체, traffic split 도입, Gateway endpoint 직접 routing을 검토했으나 초기 범위에서 채택하지 않는다.

---

# ADR-031. 2-AZ private workload VPC network baseline

- 상태: Accepted

## Context

EKS workload, RDS, S3-heavy data path, public API ingress의 network boundary와 AWS API outbound 기준이 문서에 명시되어 있지 않았다. Overall/System Deployment Architecture Diagram이 임의 가정을 피하려면 subnet, route, endpoint, ALB target, security 책임을 확정해야 한다.

## Decision

- IPv4 단일 VPC와 2개 AZ를 사용하고, 각 AZ에 Public / Private Application / Private Data Subnet을 하나씩 둔다.
- Public Subnet에는 Internet-facing ALB와 AZ별 NAT Gateway만 둔다. EKS node/Pod와 RDS에는 public IP를 부여하지 않는다.
- Private Application Subnet에는 EKS Managed Node Group, Karpenter GPU Node 및 모든 EKS workload를 둔다. 각 subnet은 같은 AZ NAT Gateway를 사용한다.
- Private Data Subnet은 RDS DB Subnet Group만 두며 VPC local route 외 internet default route를 두지 않는다. RDS는 publicly accessible이 아니다.
- S3 Gateway Endpoint를 Private Application Subnet의 baseline으로 사용한다. Interface Endpoint는 초기 도입하지 않으며, NAT 비용 또는 private-only 요구가 확인될 때 선택적으로 검토한다.
- EKS API는 private access와 승인된 operator/CI CIDR로 제한된 public access를 함께 사용한다.
- AWS Load Balancer Controller의 ALB target type은 `ip`이며 Backend API와 Inference Gateway Pod만 target으로 등록한다. KServe는 ALB target이 아닌 cluster-local Service다.
- Security Group은 VPC/node/database boundary, NetworkPolicy는 Pod-level segmentation, IAM/IRSA는 AWS API authorization을 담당한다. Security Groups for Pods는 초기 제외한다.

## Rationale

- 두 AZ와 AZ-local NAT로 availability와 cross-AZ NAT 의존성 회피를 함께 달성한다.
- private EKS/RDS 배치와 public ALB 분리로 외부 노출을 최소화한다.
- S3 Gateway Endpoint는 Dataset, artifact, InferenceLog의 대용량 VPC traffic을 NAT 비용과 불필요한 internet path에서 분리한다.
- 모든 AWS API의 Interface Endpoint를 선제 도입하지 않아 초기 비용과 운영 복잡도를 제한한다.

## Consequences

- 외부 End User의 presigned upload는 S3 Gateway Endpoint가 아니라 Internet을 통한 S3 public service endpoint 경로다.
- private workload의 비-S3 AWS API outbound는 초기 NAT에 의존한다.
- VPC CIDR과 세부 SG rule 수는 Terraform 구현에서 구체화하되 이 문서의 책임 경계를 유지한다.
- private-only EKS API를 위해 VPN, Direct Connect, bastion을 추가하지 않는다.

## Alternatives

- public worker node
- NAT-less all-interface-endpoint architecture
- private-only EKS API
- 3-AZ initial topology
- Security Groups for Pods

---

# ADR-032. RDS PostgreSQL Multi-AZ DB instance HA

- 상태: Accepted

## Context

RDS PostgreSQL은 Business State와 Execution Intent의 source of truth다. Single-AZ RDS는 Control Plane의 큰 single point of failure가 되며, 기존 문서는 HA와 DR을 함께 미해결로 남기고 있었다.

## Decision

- 운영 RDS PostgreSQL은 Multi-AZ DB instance deployment를 사용한다.
- RDS가 관리하는 Primary와 synchronous standby를 2개 AZ에 둔다. static primary AZ는 문서화하지 않는다.
- Multi-AZ DB cluster, Read Replica, RDS Proxy는 초기 baseline에 포함하지 않는다.
- failover 중 connection interruption을 예상한다. write와 Gateway authorization/state lookup은 fail closed하고, 깨진 connection을 폐기해 RDS DNS endpoint로 새 connection을 만든다. 결과가 불확실한 transaction은 actual business state를 다시 확인하며 blind mutation retry를 하지 않는다.
- DR, RTO, RPO, backup retention/PITR, cross-region recovery는 이 결정의 범위 밖으로 남긴다.

## Rationale

- synchronous standby와 automatic failover로 RDS single-AZ failure 영향을 줄인다.
- 현재 read scaling 요구나 RDS read bottleneck 근거가 없으므로 HA와 read scaling을 분리한다.
- 2-AZ network topology와 비용/복잡도에 맞는 최소 HA baseline이다.

RDS Multi-AZ DB cluster는 3-AZ topology와 readable standby를 전제로 하므로 현재 2-AZ·no-read-scaling 요구와 맞지 않는다. Read Replica와 RDS Proxy도 각각 read throughput 또는 connection storm 문제가 관측될 때 재검토한다.

## Consequences

- standby 비용과 failover 동안의 일시적 connection interruption을 감수한다.
- controller reconciliation과 기존 fail-closed 오류 계약이 failover 뒤 actual state를 복구한다.
- Multi-AZ DB instance는 read scale을 제공하지 않으며 DR 완료를 의미하지 않는다.

## Alternatives

- Single-AZ RDS
- RDS Multi-AZ DB cluster
- Read Replica
- RDS Proxy
- self-managed PostgreSQL

---

# Appendix. 결정 요약

| ADR | 결정 | 상태 |
|---|---|---|
| ADR-001 | EKS 운영 환경 | Accepted |
| ADR-002 | Control Plane / Data Plane 분리 | Accepted |
| ADR-003 | RDS PostgreSQL 기준 저장소 | Accepted |
| ADR-004 | S3 Direct Upload | Accepted |
| ADR-005 | Dataset Controller + Job | Accepted |
| ADR-006 | SQS + Transactional Outbox | Accepted |
| ADR-007 | TrainingJob Idempotency Key | Accepted |
| ADR-008 | GPU Training Kubernetes Job | Accepted |
| ADR-009 | MNG + Karpenter GPU NodePool | Accepted |
| ADR-010 | GPU Quota + PriorityClass | Accepted |
| ADR-011 | MLflow 내부 실험 추적 | Accepted |
| ADR-012 | Inference Gateway + KServe 분리 | Accepted |
| ADR-013 | KServe Standard Mode | Accepted |
| ADR-014 | Redis 초기 제외 | Accepted |
| ADR-015 | Prometheus/Grafana EKS 내부 운영 | Accepted |
| ADR-016 | S3 + Athena 분석 환경 | Accepted |
| ADR-017 | Secrets Manager + ESO | Accepted |
| ADR-018 | Fluent Bit + CloudWatch Logs | Accepted |
| ADR-019 | AuditLog / InferenceLog 분리 | Accepted |
| ADR-020 | Route 53 + WAF + ALB | Accepted |
| ADR-021 | GitHub Actions + Helm + Argo CD | Accepted |
| ADR-022 | 모듈러 모놀리스 초기 구현 | Accepted |
| ADR-023 | Docker Compose 로컬 평가 | Accepted |
| ADR-024 | Redis/KEDA/Knative/Envoy/CDN 제외 | Accepted |
| ADR-025 | 논리 Model 선생성 + 최초 TrainingJob 원자적 생성 | Accepted |
| ADR-026 | RDB 버전·소유권·삭제 정책 | Accepted |
| ADR-027 | Dataset aggregate 최신 버전 의미 분리 | Accepted |
| ADR-028 | SQS wake-up signal + RDS/Reconciler 복구 기준 | Accepted |
| ADR-029 | S3 검증 뒤 ModelVersion READY publish | Accepted |
| ADR-030 | Tabular ServingRuntime과 immutable deployment 계약 | Accepted |
| ADR-031 | 2-AZ private workload VPC network baseline | Accepted |
| ADR-032 | RDS PostgreSQL Multi-AZ DB instance HA | Accepted |
