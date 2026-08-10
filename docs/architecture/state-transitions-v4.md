# State Transition Policies

## 1. 공통 원칙

ArgMax Mini의 모든 상태 관리 엔티티에 공통으로 적용되는 원칙이다.

**기준 저장소**: 모든 엔티티의 상태는 RDS PostgreSQL에 저장한다. Kubernetes 실행 상태와 RDB 상태 간 불일치는 Controller reconciliation이 주기적으로 보정한다.

**상태 변경 주체**: 사용자는 상태값을 직접 PATCH할 수 없다. 상태 변경은 Backend API, Controller, 또는 Job이 수행한다.

**조건부 UPDATE**: 모든 상태 변경은 현재 상태를 WHERE 조건으로 포함하는 조건부 UPDATE로 처리한다.

```sql
UPDATE training_jobs
SET    status     = 'RUNNING',
       started_at = now(),
       updated_at = now()
WHERE  id         = :job_id
AND    status     = 'SCHEDULING';
```

UPDATE 결과가 0행이면 현재 상태가 예상과 다른 것이므로 중복 처리로 간주하거나 409를 반환한다.

**원자적 이벤트 기록**: TrainingJob 상태 변경과 TrainingJobEvent 기록은 같은 DB 트랜잭션에서 수행한다. 다른 엔티티의 상태 변경은 필요 시 AuditLog 또는 구조화 로그와 함께 기록한다.

**비가역적 종단 상태**: 종단 상태는 정상 운영 흐름에서 다른 상태로 전이되지 않는다. 종단 상태에서의 전이 시도는 서비스 계층에서 차단한다.

---

## 2. DatasetVersion

### 2.1 상태 정의

| 상태 | 의미 |
|---|---|
| `PENDING` | DatasetVersion이 생성됐지만 업로드가 시작되지 않음 |
| `UPLOADING` | 활성 UploadSession을 통해 파일 업로드가 진행 중 |
| `UPLOADED` | S3 객체 존재·크기 검증과 DatasetVersion metadata 반영 완료. 전체 파일 SHA-256은 아직 서버가 독립 검증하지 않음 |
| `PROCESSING` | Dataset Processing Job이 비동기로 실행 중 |
| `READY` | 처리 완료. TrainingJob 입력으로 사용 가능 |
| `FAILED` | 업로드 검증 또는 파일 처리 실패 |

### 2.2 상태 전이도

```text
PENDING → UPLOADING → UPLOADED → PROCESSING → READY
               │           │           │
               └───────────┴───────────┴──────────→ FAILED
```

FAILED 전이는 UPLOADING, UPLOADED, PROCESSING에서만 발생한다. PENDING → FAILED는 허용하지 않는다.

UPLOADING → FAILED는 non-retryable 파일 무결성 검증 실패에만 적용된다. retryable S3 기술 오류에서는 DatasetVersion이 UPLOADING을 유지한다.

### 2.3 전이 상세표

| from | to | 트리거 | 주체 | 조건 | 실패 시 | 멱등성 |
|---|---|---|---|---|---|---|
| `PENDING` | `UPLOADING` | UploadSession 생성 | Backend API | 동일 DatasetVersion에 INITIATED·UPLOADING 세션 없음 | 중복 세션 존재 시 409, 상태 유지 | - |
| `UPLOADING` | `UPLOADED` | UploadSession 완료 API | Backend API | SINGLE_PUT 객체 확인 또는 MULTIPART CompleteMultipartUpload 성공 후 HeadObject의 객체 존재·ContentLength 검증 통과 | UploadSession FAILED, DatasetVersion FAILED(non-retryable) 또는 UPLOADING 유지(retryable) | 동일 UploadSession이 COMPLETED이고 DatasetVersion이 UPLOADED 이상이면 완료 결과 반환. 다른 UploadSession이 이미 COMPLETED한 경우 409 CONFLICTING_OPERATION |
| `UPLOADED` | `PROCESSING` | Outbox 메시지 소비 | Dataset Processing Controller | DatasetVersion UPLOADED 상태 확인 | UPLOADED 유지, 재시도 | 이미 PROCESSING이면 skip |
| `PROCESSING` | `READY` | 처리 완료 | Dataset Processing Job | 파싱·변환·스키마 추출 성공, DatasetColumn 기록 완료 | - | - |
| `UPLOADING` | `FAILED` | non-retryable 업로드 검증 실패 | Backend API | 실제 크기 불일치 등 업로드 완료 단계에서 확정 가능한 파일 손상 | - | - |
| `UPLOADED` | `FAILED` | Job 생성 최대 재시도 초과 | Dataset Processing Controller | Controller가 Kubernetes Job 생성 불가 | - | - |
| `PROCESSING` | `FAILED` | 파싱·변환 오류 | Dataset Processing Job | MIME type 위반, magic number 불일치, 압축 해제 한도 초과, CSV 파싱 오류, 인코딩 오류, 행·열 수 한도 초과 | - | - |

**retryable과 non-retryable 구분 기준:**

```text
결과 불확실 오류 (UploadSession 상태 유지)
= CompleteMultipartUpload timeout, 네트워크 단절처럼 S3 처리 결과를 확정할 수 없는 경우
→ UploadSession 상태를 즉시 FAILED로 변경하지 않음
→ HeadObject 또는 ListParts로 reconciliation
→ 확인 결과에 따라 COMPLETED, 기존 상태 유지 또는 FAILED

명확하지만 재업로드 가능한 세션 오류 (DatasetVersion UPLOADING 유지)
= 복구 불가능한 upload_id 오류, 명시적인 S3 세션 오류처럼 현재 UploadSession을 계속 사용할 수 없는 경우
→ UploadSession FAILED, DatasetVersion UPLOADING 유지
→ 새 UploadSession으로 재시도 가능

non-retryable 업로드 검증 오류 (DatasetVersion FAILED)
= 실제 크기 불일치처럼 업로드 완료 단계에서 파일 자체 손상이 확정된 경우
→ UploadSession FAILED, DatasetVersion FAILED
→ 동일 DatasetVersion으로 재시도 불가
```

### 2.4 종단 상태

| 상태 | 유형 | 설명 |
|---|---|---|
| `READY` | 정상 종단 | DatasetVersion은 생성 후 불변이며 READY 이후 재처리하지 않는다 |
| `FAILED` | 실패 종단 | 동일 파일을 재처리하려면 새 DatasetVersion을 생성한다 |

### 2.5 금지 전이

| 금지 전이 | 이유 |
|---|---|
| `PENDING → FAILED` | 업로드 시작 전 실패는 DatasetVersion을 생성하지 않거나 API 요청만 실패시킨다 |
| `READY → PROCESSING` | 불변 DatasetVersion 재처리 금지 |
| `READY → FAILED` | 처리 완료 버전을 실패 처리 불가 |
| `FAILED → READY` | 실패 객체를 직접 성공 상태로 변경 불가 |
| `FAILED → PROCESSING` | 실패 버전 재처리 불가. 새 DatasetVersion 생성 필요 |

### 2.6 상태 변경 원칙

- UploadSession ABORTED 또는 EXPIRED는 DatasetVersion 상태를 변경하지 않는다. DatasetVersion은 UPLOADING을 유지하며 새 UploadSession 생성으로 재시도할 수 있다.
- UploadSession FAILED가 항상 DatasetVersion FAILED를 의미하지는 않는다. retryable 기술 오류에서는 DatasetVersion을 UPLOADING으로 유지한다. 파일 무결성 검증 실패처럼 동일 DatasetVersion을 계속 사용할 수 없는 경우에만 DatasetVersion을 FAILED로 전이한다.
- DatasetVersion이 UPLOADING이고 활성 UploadSession(INITIATED 또는 UPLOADING 상태)이 없으면 새 UploadSession을 생성할 수 있다. 이 경우 DatasetVersion 상태는 UPLOADING으로 유지되며 별도 상태 전이는 발생하지 않는다.
- FAILED 상태의 DatasetVersion은 재처리 불가하다. 동일 파일로 재시도하려면 새 DatasetVersion을 생성해야 한다.
- DatasetVersion 원본은 생성 후 불변이다. READY 이후 원본 파일은 수정하지 않는다.
- DatasetVersion의 상태는 READY에서 종결되지만, 상위 Dataset의 Soft Delete로 인해 접근이 차단될 수 있다. 이는 DatasetVersion 상태 전이가 아니다.

---

## 3. UploadSession

### 3.1 상태 정의

| 상태 | 의미 |
|---|---|
| `INITIATED` | UploadSession 생성 완료. 첫 presigned URL 발급 대기 |
| `UPLOADING` | 첫 presigned URL이 발급된 뒤 클라이언트 직접 업로드가 진행 중 |
| `COMPLETED` | SINGLE_PUT 객체 확인 또는 MULTIPART CompleteMultipartUpload와 HeadObject 크기 검증 완료. 이 세션의 파일이 DatasetVersion에 반영됨 |
| `ABORTED` | 사용자 명시적 중단 또는 시스템 중단 요청 |
| `EXPIRED` | `expires_at` 초과. 업로드가 시간 내 완료되지 않음 |
| `FAILED` | 완료 API 호출 과정에서 S3 또는 검증 기술 오류 |

**ABORTED와 FAILED 구분**:
- `ABORTED`: 사용자 또는 시스템이 명시적으로 중단한 경우
- `FAILED`: 완료 시도 또는 검증 과정에서 예외·기술 오류가 발생한 경우

### 3.2 상태 전이도

```text
INITIATED ──→ UPLOADING ──→ COMPLETED
    │              │
    └──────┬────────┘
           ├──→ ABORTED
           ├──→ EXPIRED
           └──→ FAILED
```

첫 presigned URL 발급은 항상 `INITIATED → UPLOADING`을 발생시킨다. `SINGLE_PUT`은 단일 PUT URL, `MULTIPART`는 첫 Part URL 발급 시 전이하며, 이후 Part URL 발급은 `UPLOADING` 상태를 유지한다.

### 3.3 전이 상세표

| from | to | 트리거 | 주체 | 조건 | 실패 시 | 멱등성 |
|---|---|---|---|---|---|---|
| `INITIATED` | `UPLOADING` | 첫 presigned URL 발급 | Backend API | INITIATED 상태 확인; SINGLE_PUT은 단일 PUT URL, MULTIPART는 첫 Part URL 발급 | 상태 유지 | - |
| `UPLOADING` | `COMPLETED` | 완료 API 호출 | Backend API | SINGLE_PUT은 객체 존재와 ContentLength 확인. MULTIPART는 `ceil(expected_size_bytes / part_size_bytes)`로 계산한 Part 수에 대해 제출 번호 집합이 중복 없이 `{1, ..., expected_part_count}`와 정확히 일치하고 CompleteMultipartUpload 성공 후 객체 존재와 ContentLength 확인 | FAILED 전이 | 이미 COMPLETED면 현재 세션 반환 |
| `INITIATED` | `ABORTED` | 사용자 취소 요청 | Backend API | INITIATED 상태 확인 | - | 이미 ABORTED면 현재 상태 반환 |
| `UPLOADING` | `ABORTED` | 사용자 취소 요청 | Backend API | UPLOADING 상태 확인 | - | 이미 ABORTED면 현재 상태 반환 |
| `INITIATED` | `EXPIRED` | 만료 감지 | Cleanup Job | `now() > expires_at`, INITIATED 상태 | - | 이미 EXPIRED면 skip |
| `UPLOADING` | `EXPIRED` | 만료 감지 | Cleanup Job | `now() > expires_at`, UPLOADING 상태 | - | 이미 EXPIRED면 skip |
| `INITIATED` | `FAILED` | S3 명시적 오류 | Backend API | 첫 URL 발급 전 발생한 명시적 오류 | - | - |
| `UPLOADING` | `FAILED` | S3 명시적 오류 또는 non-retryable 검증 실패 | Backend API | Single PUT 또는 CompleteMultipartUpload 명시적 실패, 객체 크기 불일치, 또는 제출 Part 번호 집합 불일치 | - | - |

**완료 처리와 checksum**: 완료 API는 `UPLOADING` 세션만 처리한다. HeadObject는 객체 존재와 ContentLength만 확인하며, S3 Multipart `ChecksumSHA256`은 composite checksum이므로 전체 파일 SHA-256과 직접 비교하지 않는다. DatasetVersion `UPLOADED`는 객체·크기 검증 완료 상태일 뿐 서버가 전체 파일 SHA-256을 독립 검증한 상태는 아니다. Dataset Processing Job이 S3 객체 전체를 스트리밍해 계산한 SHA-256과 `expected_checksum`을 비교하여 최종 무결성을 검증한다.

**CompleteMultipartUpload timeout 처리**: MULTIPART의 S3 응답이 불확실한 경우(timeout 등) 즉시 FAILED로 전이하지 않는다. HeadObject 또는 ListParts로 실제 상태를 재확인한 후 완료가 확인되면 COMPLETED, 미완료가 확인되면 재시도, 명확한 실패가 확인되면 FAILED로 전이한다.

### 3.4 종단 상태

| 상태 | 유형 | 설명 |
|---|---|---|
| `COMPLETED` | 정상 종단 | 이 세션의 파일이 DatasetVersion에 반영됨. 재사용 불가 |
| `ABORTED` | 중단 종단 | 명시적 중단. 재시도하려면 새 UploadSession 생성 |
| `EXPIRED` | 만료 종단 | 시간 초과. 재시도하려면 새 UploadSession 생성 |
| `FAILED` | 실패 종단 | 기술 오류. 재시도하려면 새 UploadSession 생성 |

### 3.5 금지 전이

| 금지 전이 | 이유 |
|---|---|
| `COMPLETED → 어떤 상태든` | 완료된 세션 재사용 불가 |
| `ABORTED → UPLOADING` | 중단된 세션 재개 불가. 새 UploadSession 생성 필요 |
| `EXPIRED → UPLOADING` | 만료된 세션 재개 불가. 새 UploadSession 생성 필요 |
| `FAILED → UPLOADING` | 실패한 세션 재개 불가. 새 UploadSession 생성 필요 |

### 3.6 상태 변경 원칙

- 하나의 DatasetVersion에 여러 UploadSession이 순차적으로 존재할 수 있다. DatasetVersion UPLOADING 상태는 개별 세션의 종단 상태(ABORTED, EXPIRED, FAILED)에 영향받지 않는다. 단, non-retryable 파일 무결성 실패 시에는 DatasetVersion도 FAILED로 전이한다.
- COMPLETED 세션은 DatasetVersion당 하나만 존재해야 한다. 완료 요청 재호출은 기존 COMPLETED 세션을 반환한다.
- Cleanup Job은 EXPIRED `MULTIPART` 세션의 S3 Multipart Upload를 AbortMultipartUpload로 정리한다. SINGLE_PUT 세션에는 Multipart 중단 호출이 없다.

---

## 4. TrainingJob

### 4.1 상태 정의

| 상태 | 의미 |
|---|---|
| `QUEUED` | TrainingJob 생성 완료. 메시지 처리 또는 GPU quota 슬롯 대기 중 |
| `SCHEDULING` | Training Controller가 Kubernetes Job 생성 중 |
| `RUNNING` | GPU Pod에서 학습 실행 중 |
| `SUCCEEDED` | 학습 완료. READY ModelVersion이 1개 이상이고 CREATING 후보가 없으며 모든 READY 후보의 publish 불변조건이 충족됨 |
| `FAILED` | 학습 실패. `error_code`와 `error_message`에 원인 기록 |
| `CANCEL_REQUESTED` | 사용자 취소 요청 접수. Controller가 처리 중 |
| `CANCELLED` | Kubernetes Job 삭제 완료 또는 실행 전 취소 처리 완료 |

### 4.2 상태 전이도

```text
QUEUED → SCHEDULING → RUNNING → SUCCEEDED
  │            │           │
  └────────────┴───────────┴──────────────→ FAILED

QUEUED ─────┐
SCHEDULING ─┼──→ CANCEL_REQUESTED ──→ CANCELLED
RUNNING ────┘              │
                           ├──────────────→ SUCCEEDED
                           │              (취소 전 학습 완료 시)
                           └──────────────→ FAILED
                                          (취소 전 학습 실패 또는 취소 재시도 한도 초과 시)
```

### 4.3 전이 상세표

| from | to | 트리거 | 주체 | 조건 | 실패 시 | 멱등성 |
|---|---|---|---|---|---|---|
| `QUEUED` | `SCHEDULING` | SQS 소비 또는 Reconciler | Training Controller | quota 가능, `status='QUEUED'` 조건부 UPDATE 성공 | QUEUED 유지, 재검사 | 이미 SCHEDULING이면 skip |
| `QUEUED` | `QUEUED` | quota 부족 | Training Controller | Kubernetes Job 미생성, QUOTA_WAITING은 최근 이벤트 기준 최소 15분 간격으로 기록하고 메시지 삭제 | Reconciler 대기 | - |
| `QUEUED` | `FAILED` | scheduling deadline 초과 | Periodic Reconciler | `created_at + 72시간` 초과, `GPU_QUOTA_WAIT_TIMEOUT` | - | 이미 FAILED면 skip |
| `SCHEDULING` | `RUNNING` | Kubernetes Pod 시작 | Training Controller | GPU Pod Running 상태 확인 | - | 이미 RUNNING이면 skip |
| `RUNNING` | `SUCCEEDED` | Kubernetes Job Complete 및 결과 확정 | Training Controller | 정상 종료, 결과 확정 대기 뒤 READY 1개 이상, CREATING 0개, 모든 READY ModelVersion의 ModelInterface·artifact URI·artifact format, 모든 ModelVersion의 model_id 일치 | - | - |
| `SCHEDULING` | `FAILED` | scheduling timeout 또는 영구 오류 | Training Controller | Pod가 30분 안에 Running이 되지 않아 `SCHEDULING_TIMEOUT`, 또는 non-retryable Job 생성 오류 | - | - |
| `RUNNING` | `FAILED` | Kubernetes Job Failed, 결과 확정 실패 또는 고아 Job | Training Controller | 최종 Pod retry 실패, `TRAINING_DEADLINE_EXCEEDED`, `KUBERNETES_JOB_LOST`, READY·CREATING 0 및 FAILED ModelVersion 또는 생성 전 실패 후보 1개 이상의 `ALL_MODEL_CANDIDATES_FAILED`, 후보 결과·실패 이벤트가 모두 없는 `NO_MODEL_CANDIDATE_PRODUCED`, 또는 10분 결과 확정 대기 뒤 `TRAINING_RESULT_INCOMPLETE` | - | - |
| `QUEUED` | `CANCEL_REQUESTED` | 취소 요청 API | Backend API | QUEUED 상태 확인 | 상태 불일치 시 409 | 이미 CANCEL_REQUESTED면 현재 상태 반환 |
| `SCHEDULING` | `CANCEL_REQUESTED` | 취소 요청 API | Backend API | SCHEDULING 상태 확인 | 상태 불일치 시 409 | 이미 CANCEL_REQUESTED면 현재 상태 반환 |
| `RUNNING` | `CANCEL_REQUESTED` | 취소 요청 API | Backend API | RUNNING 상태 확인 | 상태 불일치 시 409 | 이미 CANCEL_REQUESTED면 현재 상태 반환 |
| `CANCEL_REQUESTED` | `CANCELLED` | Kubernetes Job 삭제·종료 완료 | Training Controller | Job Complete 없이 삭제·종료되고 잔존 CREATING 후보를 `MODEL_PUBLISH_CANCELLED`로 처리 | - | 이미 CANCELLED면 skip |
| `CANCEL_REQUESTED` | `SUCCEEDED` | 취소 관찰 시 Job Complete | Training Controller | 정상 종료, 결과 확정 대기 뒤 READY 1개 이상, CREATING 0개, 모든 READY ModelVersion의 ModelInterface·artifact URI·artifact format, 모든 ModelVersion의 model_id 일치 | - | - |
| `CANCEL_REQUESTED` | `FAILED` | Job Failed 또는 결과 확정 실패 | Training Controller | Kubernetes Job Failed, `ALL_MODEL_CANDIDATES_FAILED`, `NO_MODEL_CANDIDATE_PRODUCED`, 또는 `TRAINING_RESULT_INCOMPLETE` | - | - |

### 4.4 종단 상태

| 상태 | 유형 | 설명 |
|---|---|---|
| `SUCCEEDED` | 정상 종단 | 재실행 불가. 재학습은 새 TrainingJob 생성 |
| `FAILED` | 실패 종단 | 재실행 불가. 재학습은 새 TrainingJob 생성 |
| `CANCELLED` | 취소 종단 | 재실행 불가. 재학습은 새 TrainingJob 생성 |

### 4.5 금지 전이

| 금지 전이 | 이유 |
|---|---|
| `QUEUED → FAILED` | 원칙적으로 요청 검증 실패는 TrainingJob 생성 이전에 거부한다. 단, 72시간 scheduling deadline 초과 또는 영구적 scheduling 오류는 예외다 |
| `SUCCEEDED → 어떤 상태든` | 완료된 Job 재개 불가 |
| `FAILED → RUNNING` | 실패 Job 재실행 불가. 새 TrainingJob 생성 필요 |
| `FAILED → SCHEDULING` | 동일 이유. 새 TrainingJob 생성 필요 |
| `CANCELLED → 어떤 상태든` | 취소된 Job 재개 불가 |

### 4.6 상태 변경 원칙

- 취소 요청(→ CANCEL_REQUESTED)은 Backend API가 수행하고, 실제 Kubernetes Job 삭제와 CANCELLED 전이는 Training Controller가 수행한다.
- Controller는 CANCEL_REQUESTED에서 Kubernetes Job 삭제 전에 Complete·Failed·실행 중 여부를 먼저 확인한다. Complete면 일반 결과 확정 절차를 적용하며 취소 요청이 곧 취소 성공을 보장하지 않는다.
- CANCEL_REQUESTED → SUCCEEDED는 Kubernetes Job Complete와 일반 RUNNING 성공 불변조건을 모두 충족할 때만 허용한다. CANCEL_REQUESTED → FAILED는 Kubernetes Job Failed 또는 결과 확정 오류일 때 허용한다.
- SCHEDULING 중 취소 요청이 있으면 Controller는 Job 생성을 중단하거나, 생성 직후 최신 Kubernetes Job 상태를 확인한다. Complete 또는 Failed면 해당 terminal 처리 규칙을 적용하고, terminal 상태가 아니면 Job을 삭제한다. Complete 없이 삭제·종료되면 잔존 CREATING 후보를 `MODEL_PUBLISH_CANCELLED`로 FAILED 처리한 뒤 CANCELLED로 전이한다.
- 상태 변경과 TrainingJobEvent 기록은 같은 트랜잭션에서 수행한다.
- Training Job은 학습 결과·checkpoint·ModelVersion·ModelInterface·내부 오류를 기록하지만, Kubernetes Job/Pod 생명주기 관찰에 따른 TrainingJob 최종 상태 전이는 Training Controller가 수행한다.
- `QUOTA_WAITING`, `ORPHAN_JOB_DETECTED`, `POD_RETRY_SCHEDULED`, `CHECKPOINT_CREATED`, `CHECKPOINT_INVALIDATED`, `CHECKPOINT_RESUMED`, `TRAINING_RESTARTED`, `CANDIDATE_TRAINING_FAILED`, `MODEL_VERSION_CREATING`, `MODEL_ARTIFACT_PUBLISHED`, `MODEL_VERSION_READY`, `MODEL_VERSION_FAILED`, `TRAINING_RESULT_FINALIZATION_STARTED`은 상태 전이가 없는 실행 이벤트다. 이 이벤트에만 `from_status`는 현재 상태, `to_status`는 NULL을 기록한다.
- `GPU_QUOTA_WAIT_TIMEOUT`, `SCHEDULING_TIMEOUT`, `KUBERNETES_JOB_LOST`, `TRAINING_DEADLINE_EXCEEDED`, `TRAINING_RESULT_INCOMPLETE`, `ALL_MODEL_CANDIDATES_FAILED`, `NO_MODEL_CANDIDATE_PRODUCED`은 상태 전이를 동반하는 실패 이벤트 또는 오류 코드다.
- RUNNING Job이 없을 때 grace는 최초 `ORPHAN_JOB_DETECTED.occurred_at`부터 5분이다. 단일 Controller의 재삽입은 금지하고 다중 Controller의 관측 중복은 허용한다.

---

## 5. ModelVersion

### 5.1 상태 정의

| 상태 | 의미 |
|---|---|
| `CREATING` | Training Job이 model artifact 생성 중 |
| `READY` | final artifact 검증과 ModelInterface finalization 완료. InferenceDeployment에 사용 가능 |
| `FAILED` | artifact 생성 실패. `error_code`와 `error_message`에 원인 기록 |
| `ARCHIVED` | 운영상 비활성화. 신규 InferenceDeployment 생성 불가 |

### 5.2 상태 전이도

```text
CREATING → READY → ARCHIVED
    │
    └──→ FAILED
```

### 5.3 전이 상세표

| from | to | 트리거 | 주체 | 조건 | 실패 시 | 멱등성 |
|---|---|---|---|---|---|---|
| `CREATING` | `READY` | 정상 finalization | Training Job 또는 Job 종료 후 Training Controller/Reconciler | final artifact·manifest 검증, `artifact_uri`·`artifact_format` 기록, 정확히 하나의 ModelInterface, TrainingJob과 model_id 일치 | - | 동일 정보의 기존 READY면 성공 |
| `CREATING` | `FAILED` | 실행 중 publish 오류 | Training Job | upload·checksum·manifest 오류 또는 `MODEL_INTERFACE_CONFLICT`; 직렬화·로컬 ModelInterface 생성·검증 오류는 row 생성 전 후보 실패 | - | 이미 FAILED면 skip |
| `CREATING` | `FAILED` | 고아 publish·timeout | Training Controller/Reconciler | `MODEL_ARTIFACT_LOST` 또는 30분 CREATING timeout | - | 이미 FAILED면 skip |
| `CREATING` | `FAILED` | 결과 확정 timeout | Training Controller/Reconciler | Job Complete 후 10분 초과, `TRAINING_RESULT_FINALIZATION_TIMEOUT` | - | 이미 FAILED면 skip |
| `CREATING` | `FAILED` | 취소 중 미완료 publish 중단 | Training Job 또는 Training Controller/Reconciler | staging 검증 미완료, `MODEL_PUBLISH_CANCELLED` | - | 이미 FAILED면 skip |
| `READY` | `ARCHIVED` | 수동 또는 운영 정책 | Backend API | READY 상태 확인 | 상태 불일치 시 409 | 이미 ARCHIVED면 현재 상태 반환 |

### 5.4 안정 상태 및 종단 상태

| 상태 | 유형 | 설명 |
|---|---|---|
| `READY` | 활성 안정 상태 | ARCHIVED 전이 전까지 InferenceDeployment에 사용 가능. 종단 상태가 아니다 |
| `FAILED` | 실패 종단 상태 | 재처리 불가. 새 TrainingJob을 생성해야 한다 |
| `ARCHIVED` | 운영 종단 상태 | 초기 범위에서 복원 정책 없음 |

### 5.5 금지 전이

| 금지 전이 | 이유 |
|---|---|
| `ARCHIVED → READY` | 초기 범위에서 복원 정책 없음. 필요 시 새 TrainingJob 실행 |
| `ARCHIVED → CREATING` | 동일 이유 |
| `READY → CREATING` | 완성된 ModelVersion 재처리 불가 |
| `READY → FAILED` | 정상 artifact를 실패 처리 불가 |
| `FAILED → READY` | 실패 artifact를 직접 성공 처리 불가 |
| `FAILED → ARCHIVED` | 초기 범위에서 FAILED 버전 정리 기능 미지원. FAILED는 영구 실패 종단 상태 |

### 5.6 상태 변경 원칙

- Training Job이 실행 중이면 ModelVersion publish와 직접 READY/FAILED 전이를 수행한다. Kubernetes Job 종료 뒤 잔존 CREATING ModelVersion은 Training Controller/Reconciler가 artifact 상태와 timeout을 검사해 READY finalization을 재시도하거나 FAILED로 정리한다. READY finalization은 ModelInterface 생성·검증과 하나의 DB 트랜잭션에서 수행하며 사용자는 이 전이에 관여하지 않는다.
- READY → ARCHIVED 전이는 사용자 또는 운영자가 Backend API를 통해 요청한다.
- FAILED는 영구 실패 종단 상태이며 초기 범위에서 다른 상태로 전이하지 않는다.
- InferenceDeployment 생성 시 참조하는 ModelVersion은 READY 상태여야 한다. 서비스 계층에서 검증한다.
- 하나의 TrainingJob에서 0개 이상의 ModelVersion이 생성될 수 있다. 모든 ModelVersion의 `model_id`는 TrainingJob의 `model_id`와 동일해야 한다.
- `candidate_number`는 TrainingJob 내부의 결정된 후보 순번이며 완료 순서·성능 순위가 아니다. Pod retry는 `(training_job_id, candidate_number)`의 기존 row와 `model_version_id`를 재사용한다.
- `version_number`는 Model 내부 공개 순번이며 FAILED도 번호를 소비할 수 있고 gap을 허용한다. `FAILED → CREATING`과 `FAILED → READY`는 금지한다.
- TrainingJob이 `TRAINING_RESULT_INCOMPLETE`로 FAILED되면 같은 reconciliation 과정에서 잔존 CREATING ModelVersion을 `TRAINING_RESULT_FINALIZATION_TIMEOUT`으로 FAILED 처리한다. 이후 해당 ModelVersion의 READY 전이는 금지한다.

---

## 6. InferenceDeployment

### 6.1 상태 정의

| 상태 | 의미 |
|---|---|
| `PENDING` | 배포 요청 수신. Deployment Controller 처리 대기 |
| `DEPLOYING` | Controller가 KServe InferenceService 생성 중 |
| `READY` | KServe readiness 확인 완료. 추론 요청 처리 가능 |
| `UPDATING` | 배포 변경 요청 처리 중 |
| `FAILED` | DEPLOYING 생성·복구 실패, UPDATING rollback 실패·timeout, 또는 DELETING 삭제 실패·timeout으로 도달. DELETING으로만 전이 가능 |
| `DELETING` | KServe InferenceService 삭제 중 |
| `DELETED` | 삭제 완료 |

### 6.2 상태 전이도

```text
PENDING → DEPLOYING → READY
               │          │
               └──→ FAILED├──→ DEPLOYING (resource lost / immutable drift)
                          └──→ UPDATING → READY
                                      │
                                      └──→ FAILED (rollback failure / timeout)

PENDING ───┐
DEPLOYING ─┤
READY ─────┼──→ DELETING → DELETED
UPDATING ──┤      │
FAILED ────┘      └──→ FAILED (delete failure / timeout)
```

FAILED에서는 DELETING으로만 전이할 수 있다. 직접 재시도는 허용하지 않는다. 재배포는 새 InferenceDeployment를 생성한다.

### 6.3 전이 상세표

| from | to | 트리거 | 주체 | 조건 | 실패 시 | 멱등성 |
|---|---|---|---|---|---|---|
| `PENDING` | `DEPLOYING` | Controller 요청 감지 | Deployment Controller | PENDING 상태 확인 | PENDING 유지, 재시도 | 이미 DEPLOYING이면 skip |
| `DEPLOYING` | `READY` | KServe readiness 확인 | Deployment Controller | InferenceService Ready 상태 | - | 이미 READY면 skip |
| `DEPLOYING` | `FAILED` | KServe 생성 오류 | Deployment Controller | InferenceService 생성 실패 또는 timeout | - | - |
| `READY` | `UPDATING` | 배포 변경 요청 | Backend API | READY 상태 확인 | 상태 불일치 시 409 | - |
| `READY` | `DEPLOYING` | resource 유실 또는 immutable drift | Deployment Controller | endpoint 제거 후 reconcile | - | - |
| `READY` | `UPDATING` | replica-only drift | Deployment Controller | desired/applied 차이 감지 | - | - |
| `UPDATING` | `READY` | KServe 변경 완료 | Deployment Controller | InferenceService Ready 상태 | - | 이미 READY면 skip |
| `UPDATING` | `FAILED` | rollback 실패 또는 rollback timeout | Deployment Controller | update 실패/timeout 뒤 마지막 applied replica로 복원했으나 실패 또는 300초 초과, `DEPLOYMENT_ROLLBACK_FAILED` | - | - |
| `PENDING` | `DELETING` | 삭제 요청 | Backend API | PENDING 상태 확인 | 상태 불일치 시 409 | 이미 DELETING이면 현재 상태 반환 |
| `DEPLOYING` | `DELETING` | 삭제 요청 | Backend API | DEPLOYING 상태 확인 | 상태 불일치 시 409 | 이미 DELETING이면 현재 상태 반환 |
| `READY` | `DELETING` | 삭제 요청 | Backend API | READY 상태 확인 | 상태 불일치 시 409 | 이미 DELETING이면 현재 상태 반환 |
| `UPDATING` | `DELETING` | 삭제 요청 | Backend API | UPDATING 상태 확인 | 상태 불일치 시 409 | 이미 DELETING이면 현재 상태 반환 |
| `FAILED` | `DELETING` | 삭제 요청 | Backend API | FAILED 상태 확인 | 상태 불일치 시 409 | 이미 DELETING이면 현재 상태 반환 |
| `DELETING` | `DELETED` | KServe 리소스 삭제 완료 | Deployment Controller | InferenceService 없음 확인 | - | 이미 DELETED면 skip |
| `DELETING` | `FAILED` | delete timeout 또는 영구 삭제 오류 | Deployment Controller | `DEPLOYMENT_DELETE_TIMEOUT` 등 | - | - |

### 6.4 종단 상태

| 상태 | 유형 | 설명 |
|---|---|---|
| `DELETED` | 삭제 종단 | 복원 정책 없음. 재배포는 새 InferenceDeployment 생성 |
| `FAILED` | 실패 준종단 | DELETING으로만 전이 가능. 직접 재시도 불가. 재배포는 새 InferenceDeployment 생성 |

### 6.5 금지 전이

| 금지 전이 | 이유 |
|---|---|
| `FAILED → DEPLOYING` | 직접 재시도 불가. 재배포는 새 InferenceDeployment 생성 |
| `FAILED → UPDATING` | 초기 생성 실패 상태에서 UPDATING은 의미 불명확. 재배포는 새 InferenceDeployment 생성 |
| `DELETED → 어떤 상태든` | 삭제된 배포 복원 정책 없음 |
| `READY → FAILED` | 직접 전이 불가. UPDATING 경유 필요 |
| `UPDATING → DEPLOYING` | 변경 흐름은 UPDATING → READY 또는 FAILED로만 전이 |

UPDATING은 기존 endpoint가 유지되는 동안 추론 가능하다. update 실패 또는 timeout은 즉시 FAILED가 아니라 마지막 applied replica 설정으로 rollback한다. rollback 실패 또는 300초 timeout일 때만 `DEPLOYMENT_ROLLBACK_FAILED`로 UPDATING → FAILED 전이하며 applied 값은 마지막 검증 성공값을 유지한다.

### 6.6 상태 변경 원칙

- FAILED 상태의 InferenceDeployment는 DELETING으로만 전이할 수 있다. 직접 재시도(FAILED → DEPLOYING 또는 FAILED → UPDATING)는 허용하지 않는다. 재배포는 새 InferenceDeployment를 생성한다.
- DEPLOYING 또는 UPDATING 중 삭제 요청(→ DELETING)이 가능하다. Controller는 DELETING 상태를 감지하면 진행 중인 KServe 작업을 중단하고 삭제를 수행한다.
- `kserve_namespace`와 `kserve_service_name`은 DEPLOYING 전이 시 채워진다. PENDING 상태에서는 NULL이다.
- DELETED 전이 후 KServe InferenceService 부재를 확인하고 기록한다.

---

## 7. 구현 및 테스트 적용 기준

### 7.1 상태 변경 API 제공 여부

| 엔티티 | 사용자 직접 상태 변경 | 허용 전이 |
|---|---|---|
| DatasetVersion | 불가 | Backend API와 Job이 자동 전이 |
| UploadSession | 제한적 | 완료(→ COMPLETED), 중단(→ ABORTED) 요청만 허용 |
| TrainingJob | 제한적 | 취소 요청(→ CANCEL_REQUESTED)만 허용 |
| ModelVersion | 제한적 | 비활성화(→ ARCHIVED) 요청만 허용 |
| InferenceDeployment | 제한적 | 변경(→ UPDATING), 삭제(→ DELETING) 요청만 허용 |

### 7.2 잘못된 전이의 HTTP 응답

| 상황 | HTTP 응답 | 오류 코드 |
|---|---|---|
| 금지 전이 요청 (사용자) | `409 Conflict` | `INVALID_STATE_TRANSITION` |
| 존재하지 않는 리소스 | `404 Not Found` | `RESOURCE_NOT_FOUND` |
| 동일 리소스·동일 명령 재호출 (멱등) | `200 OK` | 현재 리소스 반환 |
| 상충하는 요청이 이미 결과를 점유 | `409 Conflict` | `CONFLICTING_OPERATION` |
| Controller 내부 상태 불일치 | 조건부 UPDATE 0행 | skip 또는 reconciliation 대기 |

멱등 응답 조건: 동일 리소스에 대한 동일 명령의 재호출은 200 OK로 처리한다. 다른 리소스 또는 상충하는 요청이 이미 결과를 점유한 경우(예: 다른 UploadSession이 COMPLETED인데 새 완료 요청)는 409 Conflict를 반환한다.

### 7.3 필수 테스트 케이스

**정상 경로**

- 각 엔티티의 전체 정상 상태 전이 순서 검증
- 멱등 호출: 동일 완료 요청 재호출 시 현재 상태 반환 확인

**비정상 경로**

- 금지 전이 시도 → 409 반환 확인
- 종단 상태에서 재전이 시도 → 409 반환 확인
- 중간 상태에서 취소 또는 삭제 요청 → 정상 처리 확인

**Controller 중복 처리**

- Controller가 동일 메시지를 두 번 수신 → 조건부 UPDATE 0행으로 skip 확인
- RDB 상태와 Kubernetes 상태 불일치 → reconciliation 후 올바른 상태로 수렴 확인

**TrainingJob 취소 경계**

- CANCEL_REQUESTED 도달 직전에 학습 완료 → SUCCEEDED 전이 확인
- CANCEL_REQUESTED 도달 직전에 학습 실패 → FAILED 전이 확인
- SCHEDULING 중 취소 요청 → Controller가 Kubernetes Job terminal 상태를 먼저 확인하고, terminal이 아니면 삭제 후 CANCELLED 전이 확인

**TrainingJob quota 대기**

- QUEUED 상태가 72시간을 초과하면 Reconciler가 GPU_QUOTA_WAIT_TIMEOUT으로 FAILED 전이하는지 확인
- Reconciler 재시작 뒤 기존 QUEUED Job을 RDS 기준으로 재검사하는지 확인

**TrainingJob ORPHAN_JOB_DETECTED**

- 최초 이벤트 기준 5분 grace 경과 뒤에도 Kubernetes Job이 없으면 KUBERNETES_JOB_LOST로 FAILED 전이하는지 확인
- 5분 안에 Job이 복구되면 RUNNING을 유지하는지 확인

**ModelVersion publish와 결과 확정**

- Pod retry가 같은 `(training_job_id, candidate_number)` 및 `model_version_id`를 재사용하는지 확인
- final artifact만 존재하거나 ModelInterface가 없으면 READY 전이가 거부되는지 확인
- 동일 ModelInterface 재finalization은 성공하고, 다른 schema는 `MODEL_INTERFACE_CONFLICT`로 FAILED 처리되는지 확인
- Job Complete 뒤 `TRAINING_RESULT_FINALIZATION_STARTED`의 가장 이른 시각부터 10분을 계산하는지 확인
- READY 1개 이상·CREATING 0개·FAILED 후보 포함 시 SUCCEEDED, READY 0개·FAILED만 있으면 `ALL_MODEL_CANDIDATES_FAILED`, 후보가 없으면 `NO_MODEL_CANDIDATE_PRODUCED`인지 확인
- 10분 뒤에도 CREATING이 남으면 `TRAINING_RESULT_INCOMPLETE`인지, 후보별 30분 CREATING timeout과 구분되는지 확인
- CANCELLED TrainingJob에서 staging 검증을 끝낸 후보만 READY까지 publish되고 InferenceDeployment 대상이 되는지 확인
- Job Complete 후 10분 동안 CREATING이 남으면 TrainingJob은 `TRAINING_RESULT_INCOMPLETE`, 잔존 후보는 `TRAINING_RESULT_FINALIZATION_TIMEOUT`으로 각각 FAILED되는지 확인
- TrainingJob FAILED 뒤 해당 후보가 READY로 전이하지 않는지, Job 종료 뒤 유효 final artifact가 있으면 10분 안에 Reconciler가 READY finalization을 재시도하는지 확인
- CANCEL_REQUESTED 이후 신규 CREATING row가 생성되지 않고 staging 검증 미완료 후보가 `MODEL_PUBLISH_CANCELLED`로 FAILED되는지 확인
- 직렬화 또는 로컬 ModelInterface 생성·검증 실패 시 ModelVersion row 없이 `CANDIDATE_TRAINING_FAILED`가 기록되는지 확인
- 동일 candidate의 동시 INSERT 중 Unique 충돌 흐름이 rollback·재조회 뒤 기존 row·ID·version_number를 재사용하는지 확인
- CANCEL_REQUESTED에서 Job Complete를 삭제보다 먼저 판정하고, graceful termination 중 Complete면 결과 확정으로 들어가며, 삭제 완료 시 잔존 CREATING을 `MODEL_PUBLISH_CANCELLED`로 닫는지 확인
- checkpoint final URI가 checkpoint_id 기반이고 sequence는 final 객체 검증 뒤 DB 순번으로 할당되는지 확인
- 모든 후보가 ModelVersion 생성 전에 실패하면 `ALL_MODEL_CANDIDATES_FAILED`인지, 중복 실패 이벤트는 distinct candidate_number로 한 번만 집계되는지 확인
- 같은 candidate에 ModelVersion row와 생성 전 실패 이벤트가 함께 있으면 이중 집계하지 않는지, 후보 결과와 실패 이벤트가 모두 없을 때만 `NO_MODEL_CANDIDATE_PRODUCED`인지 확인
- Checkpoint publish 재호출이 같은 `TrainingCheckpoint.id`를 사용하고 동시 PK 충돌 뒤 기존 row를 재조회하는지, 다른 metadata의 동일 ID가 `CHECKPOINT_ID_CONFLICT`인지 확인
- SCHEDULING 취소에서 Kubernetes Job terminal 상태를 삭제보다 먼저 확인하는지 확인

**UploadSession/DatasetVersion FAILED 연계**

- 명확한 retryable 세션 실패 → UploadSession FAILED, DatasetVersion UPLOADING 유지 확인
- 결과 불확실 timeout → 세션 상태 유지, reconciliation 후 COMPLETED 또는 FAILED 확인
- non-retryable checksum 불일치 → UploadSession FAILED, DatasetVersion FAILED 확인
