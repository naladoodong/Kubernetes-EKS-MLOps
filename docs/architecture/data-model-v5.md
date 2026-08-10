# ArgMax Mini Data Model

## 1. 문서 목적

이 문서는 ArgMax Mini RDB 스키마의 단일 기준문서다.

다음 항목을 정의한다.

- 엔티티 역할과 관계
- PostgreSQL 컬럼·타입·NULL·기본값
- Primary Key와 Foreign Key
- FK별 `ON DELETE`
- Unique 및 Partial Unique Index
- Check Constraint
- 성능 인덱스
- 상태 집합과 교차 엔티티 검증
- 버전 번호 동시성
- Soft Delete 및 물리 삭제
- 로컬 평가 사용자 seed
- API aggregate 조회 의미

전체 PostgreSQL DDL과 Alembic migration은 이 문서를 기준으로 작성한다.

---

## 2. 문서 간 책임

| 문서 | 책임 |
|---|---|
| `system-context-v3.md` | 시스템 경계, 컴포넌트, 요청 흐름, 운영·로컬 환경 |
| `architecture-decisions-v3.md` | 주요 선택과 대안, 선택 근거, 결과 |
| `data-model-v5.md` | RDB 엔티티·컬럼·관계·제약·인덱스의 단일 기준 |
| `database/schema-v2.sql` | 실행 가능한 PostgreSQL DDL |
| ERD | `data-model-v5.md`의 관계를 시각화 |

문서 간 내용이 충돌하면 RDB 상세 사항은 `data-model-v5.md`를 우선한다.

---

## 3. 공통 규칙

### 3.1 식별자

모든 PK는 UUID v4다.

```sql
UUID NOT NULL DEFAULT gen_random_uuid()
```

PostgreSQL 확장:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

### 3.2 시간

모든 운영 시간은 `TIMESTAMPTZ`를 사용한다.

- DB 저장 기준: UTC
- `created_at`: `NOT NULL DEFAULT now()`
- 수정 가능한 엔티티의 `updated_at`: `NOT NULL DEFAULT now()`
- `updated_at`은 애플리케이션 서비스가 UPDATE 시 명시적으로 갱신
- 초기 구현에서는 DB trigger를 사용하지 않음

### 3.3 상태값

PostgreSQL native ENUM 대신 `VARCHAR + CHECK`를 사용한다.

이유:

- Alembic migration 단순화
- 상태 추가·변경 용이
- DB 허용값 통제 가능

### 3.4 JSONB

구조가 알고리즘·모델·데이터 타입에 따라 달라지는 값에만 사용한다.

- `hyperparameters`
- `statistics_json`
- `metrics_json`
- JSON Schema
- `traffic_config_json`
- `metadata_json`
- `payload_json`

### 3.5 문자열 정규화

사용자 입력 이름은 API에서 `strip()`한 후 저장한다.

대소문자 무관 유일성 비교에는 다음 표현을 사용한다.

```sql
lower(btrim(column_name))
```

---

## 4. 전체 엔티티와 관계

```text
User
├── Dataset
│   └── DatasetVersion
│       ├── DatasetColumn
│       ├── UploadSession
│       └── TrainingJob
│           ├── TrainingJobEvent
│           ├── TrainingCheckpoint
│           └── ModelVersion
│
├── Model
│   ├── TrainingJob
│   └── ModelVersion
│       ├── ModelInterface
│       └── InferenceDeployment  ← ModelVersion FK
│
├── InferenceDeployment          ← direct user_id FK
└── AuditLog

OutboxEvent
```

| 부모 | 자식 | 관계 |
|---|---|---:|
| User | Dataset | 1:N |
| Dataset | DatasetVersion | 1:N |
| DatasetVersion | DatasetColumn | 1:N |
| DatasetVersion | UploadSession | 1:0..N |
| User | Model | 1:N |
| User | TrainingJob | 1:N |
| Model | TrainingJob | 1:N |
| DatasetVersion | TrainingJob | 1:N |
| DatasetColumn | TrainingJob | 1:0..N |
| TrainingJob | TrainingJobEvent | 1:N |
| TrainingJob | TrainingCheckpoint | 1:N |
| TrainingJob | ModelVersion | 1:0..N |
| Model | ModelVersion | 1:N |
| ModelVersion | ModelInterface | 1:1 |
| User | InferenceDeployment | 1:N |
| ModelVersion | InferenceDeployment | 1:0..N |
| User | AuditLog | 1:0..N |

> InferenceDeployment는 배포 대상인 ModelVersion과 소유자인 User를 모두 직접 참조한다. `user_id`는 사용자별 인가·조회·이름 유일성에 사용하며, 생성 시 ModelVersion이 속한 Model의 `user_id`와 일치하도록 서비스 계층에서 검증한다.

---

# 5. 엔티티 정의

## 5.1 `users`

### 역할

인증 구현체가 아니라 Dataset, Model, TrainingJob, InferenceDeployment의 소유권 기준이다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
|---|---|---:|---|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` | PK |
| `email` | `VARCHAR(320)` | 불가 | 없음 | 사용자 식별 이메일 |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` | 생성 시각 |

### 제약과 인덱스

```sql
PRIMARY KEY (id)
CHECK (length(btrim(email)) > 0)
```

```sql
CREATE UNIQUE INDEX uq_users_email_ci
ON users (lower(btrim(email)));
```

이메일 문법은 Pydantic에서 검증한다.

### 로컬 평가 seed

```text
id    = 00000000-0000-4000-8000-000000000001
email = evaluator@argmax-mini.local
```

---

## 5.2 `datasets`

### 역할

여러 파일 버전을 묶는 논리적 데이터셋이다. 파일 메타데이터와 처리 상태를 저장하지 않는다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `user_id` | `UUID` | 불가 | 없음 |
| `name` | `VARCHAR(255)` | 불가 | 없음 |
| `description` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `deleted_at` | `TIMESTAMPTZ` | 가능 | `NULL` |

### FK

```sql
FOREIGN KEY (user_id)
REFERENCES users(id)
ON DELETE RESTRICT
```

### 제약과 인덱스

```sql
CHECK (length(btrim(name)) > 0)
```

```sql
CREATE UNIQUE INDEX uq_datasets_active_user_name
ON datasets (user_id, lower(btrim(name)))
WHERE deleted_at IS NULL;
```

### 삭제 정책

- `deleted_at IS NULL`: 활성
- 값 존재: Soft Delete
- 복원 기간: 30일
- 삭제된 이름 재사용 허용
- 복원 시 동일 활성 이름이 있으면 `409 Conflict`
- DatasetVersion이 TrainingJob에 사용됐다면 물리 삭제는 FK RESTRICT로 차단

### 제외 컬럼

- `status`
- `storage_uri`
- `file_format`
- `size_bytes`
- `schema_json`
- `current_version_id`

---

## 5.3 `dataset_versions`

### 역할

특정 Dataset에 업로드된 하나의 불변 원본 파일 버전과 처리 결과다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `dataset_id` | `UUID` | 불가 | 없음 |
| `version_number` | `INTEGER` | 불가 | 없음 |
| `original_filename` | `VARCHAR(512)` | 불가 | 없음 |
| `file_format` | `VARCHAR(16)` | 불가 | 없음 |
| `mime_type` | `VARCHAR(255)` | 가능 | `NULL` |
| `size_bytes` | `BIGINT` | 가능 | `NULL` |
| `original_storage_uri` | `TEXT` | 가능 | `NULL` |
| `processed_storage_uri` | `TEXT` | 가능 | `NULL` |
| `checksum_algorithm` | `VARCHAR(16)` | 불가 | `'SHA256'` |
| `checksum` | `VARCHAR(128)` | 가능 | `NULL` |
| `row_count` | `BIGINT` | 가능 | `NULL` |
| `column_count` | `INTEGER` | 가능 | `NULL` |
| `status` | `VARCHAR(32)` | 불가 | `'PENDING'` |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `error_message` | `TEXT` | 가능 | `NULL` |
| `processing_started_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `processing_finished_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (dataset_id)
REFERENCES datasets(id)
ON DELETE CASCADE
```

### 상태

```text
PENDING
→ UPLOADING
→ UPLOADED
→ PROCESSING
→ READY

실패 → FAILED
```

### Check Constraint

```sql
CHECK (length(btrim(original_filename)) > 0)
CHECK (version_number > 0)
CHECK (file_format IN ('CSV', 'XLSX'))
CHECK (checksum_algorithm = 'SHA256')
CHECK (size_bytes IS NULL OR size_bytes >= 0)
CHECK (row_count IS NULL OR row_count >= 0)
CHECK (column_count IS NULL OR column_count >= 0)
CHECK (
  status IN (
    'PENDING','UPLOADING','UPLOADED',
    'PROCESSING','READY','FAILED'
  )
)
CHECK (
  processing_finished_at IS NULL
  OR processing_started_at IS NOT NULL
)
CHECK (
  processing_finished_at IS NULL
  OR processing_finished_at >= processing_started_at
)
```

상태별 필수 필드 조합은 처리 서비스가 하나의 원자적 UPDATE에서 검증한다.

### Unique

```sql
UNIQUE (dataset_id, version_number)
```

### 인덱스

```sql
CREATE INDEX idx_dataset_versions_dataset_status_version
ON dataset_versions (dataset_id, status, version_number DESC);
```

```sql
CREATE INDEX idx_dataset_versions_status_created
ON dataset_versions (status, created_at);
```

### 파일 형식 의미

`file_format`은 사용자가 업로드한 원본 형식이다. 내부 Parquet 처리본은 `processed_storage_uri`로 표현한다.

CSV/XLSX 이외 입력은 API에서 `422 Unprocessable Entity`로 거부한다.

---

## 5.4 `dataset_columns`

### 역할

DatasetVersion 처리 결과로 생성된 컬럼별 스키마와 통계다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `dataset_version_id` | `UUID` | 불가 | 없음 |
| `name` | `VARCHAR(255)` | 불가 | 없음 |
| `ordinal_position` | `INTEGER` | 불가 | 없음 |
| `data_type` | `VARCHAR(32)` | 불가 | 없음 |
| `physical_type` | `VARCHAR(64)` | 가능 | `NULL` |
| `is_nullable` | `BOOLEAN` | 불가 | `false` |
| `null_count` | `BIGINT` | 불가 | `0` |
| `distinct_count` | `BIGINT` | 가능 | `NULL` |
| `statistics_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (dataset_version_id)
REFERENCES dataset_versions(id)
ON DELETE CASCADE
```

### Check Constraint

```sql
CHECK (length(btrim(name)) > 0)
CHECK (ordinal_position > 0)
CHECK (null_count >= 0)
CHECK (distinct_count IS NULL OR distinct_count >= 0)
CHECK (
  data_type IN (
    'STRING','INTEGER','FLOAT','BOOLEAN',
    'DATE','DATETIME','CATEGORY','UNKNOWN'
  )
)
```

### Unique

```sql
UNIQUE (dataset_version_id, ordinal_position)
```

```sql
CREATE UNIQUE INDEX uq_dataset_columns_version_name_ci
ON dataset_columns (
  dataset_version_id,
  lower(btrim(name))
);
```

`Age`와 `age`는 같은 버전에서 중복으로 취급한다. 파일 처리 단계에서 먼저 `DUPLICATE_COLUMN_NAME`으로 실패시키며 DB 인덱스는 최종 방어선이다.

---

## 5.5 `upload_sessions`

### 역할

DatasetVersion 원본 파일의 개별 S3 직접 업로드 시도다. `upload_method`에 따라 단일 PUT 또는 Multipart Upload를 사용한다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `dataset_version_id` | `UUID` | 불가 | 없음 |
| `status` | `VARCHAR(32)` | 불가 | `'INITIATED'` |
| `storage_key` | `TEXT` | 불가 | 없음 |
| `upload_method` | `VARCHAR(16)` | 불가 | 없음 |
| `upload_id` | `TEXT` | 가능 | `NULL` |
| `expected_size_bytes` | `BIGINT` | 가능 | `NULL` |
| `expected_checksum_algorithm` | `VARCHAR(16)` | 불가 | `'SHA256'` |
| `expected_checksum` | `VARCHAR(128)` | 가능 | `NULL` |
| `part_size_bytes` | `INTEGER` | 가능 | `NULL` |
| `expires_at` | `TIMESTAMPTZ` | 불가 | 없음 |
| `completed_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `aborted_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `error_message` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (dataset_version_id)
REFERENCES dataset_versions(id)
ON DELETE CASCADE
```

### 상태

```text
INITIATED
UPLOADING
COMPLETED
ABORTED
EXPIRED
FAILED
```

### Check Constraint

```sql
CHECK (length(btrim(storage_key)) > 0)
CHECK (
  status IN (
    'INITIATED','UPLOADING','COMPLETED',
    'ABORTED','EXPIRED','FAILED'
  )
)
CHECK (expected_checksum_algorithm = 'SHA256')
CHECK (expected_size_bytes IS NULL OR expected_size_bytes >= 0)
CHECK (part_size_bytes IS NULL OR part_size_bytes > 0)
CHECK (upload_method IN ('SINGLE_PUT', 'MULTIPART'))
CHECK (
  (upload_method = 'SINGLE_PUT'
    AND upload_id IS NULL
    AND part_size_bytes IS NULL)
  OR
  (upload_method = 'MULTIPART'
    AND upload_id IS NOT NULL
    AND part_size_bytes IS NOT NULL)
)
CHECK (expires_at > created_at)
CHECK (completed_at IS NULL OR completed_at >= created_at)
CHECK (aborted_at IS NULL OR aborted_at >= created_at)
```

### Unique

```sql
CREATE UNIQUE INDEX uq_upload_sessions_upload_id
ON upload_sessions (upload_id)
WHERE upload_id IS NOT NULL;
```

```sql
CREATE UNIQUE INDEX uq_upload_sessions_active_version
ON upload_sessions (dataset_version_id)
WHERE status IN ('INITIATED', 'UPLOADING');
```

```sql
CREATE UNIQUE INDEX uq_upload_sessions_completed_version
ON upload_sessions (dataset_version_id)
WHERE status = 'COMPLETED';
```

```sql
CREATE INDEX idx_upload_sessions_dataset_version
ON upload_sessions (dataset_version_id);
```

### 완료 처리 경계

### 업로드 경로와 불변조건

- 서비스 계층은 `expected_size_bytes`를 반드시 양수로 검증한다.
- `16 MiB = 16 * 1024 * 1024 bytes`를 기준으로, `expected_size_bytes <= 16 MiB`는 `SINGLE_PUT`, `expected_size_bytes > 16 MiB`는 `MULTIPART`를 선택한다.
- `SINGLE_PUT`은 `upload_id`와 `part_size_bytes`가 모두 `NULL`이며, 단일 PUT용 presigned URL을 사용한다.
- `MULTIPART`는 S3 Multipart Upload ID와 양의 `part_size_bytes`를 저장한다.
- `expected_part_count`는 저장 컬럼이 아니다. Multipart 완료 시 `ceil(expected_size_bytes / part_size_bytes)`로 계산하고, 제출 Part 번호 집합이 중복 없이 정확히 `{1, 2, ..., expected_part_count}`와 같아야 한다.

동기 API:

1. `SINGLE_PUT`은 Multipart Part 목록이나 `CompleteMultipartUpload` 호출 없이 객체 업로드를 완료한다. `MULTIPART`은 검증된 Part 번호 집합으로 S3 `CompleteMultipartUpload`를 호출한다.
2. `HeadObject`로 객체 존재 여부와 `ContentLength`를 확인한다. 이 단계에서 전체 파일 SHA-256을 직접 비교하지 않는다.
3. UploadSession `COMPLETED`
4. DatasetVersion 원본 URI·크기·클라이언트가 제출한 `expected_checksum` 기록
5. DatasetVersion `UPLOADED`
6. OutboxEvent 생성

비동기 Job:

- S3 객체 전체를 스트리밍하여 전체 파일 SHA-256을 계산하고 `expected_checksum`과 비교해 최종 무결성을 검증한다. S3 Multipart `ChecksumSHA256`은 composite checksum이므로 전체 파일 SHA-256과 직접 비교하지 않는다.
- CSV/XLSX 파싱
- Parquet 변환
- DatasetColumn 생성
- READY/FAILED 반영

---

## 5.6 `models`

### 역할

여러 TrainingJob과 ModelVersion을 묶는 논리 모델이다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `user_id` | `UUID` | 불가 | 없음 |
| `name` | `VARCHAR(255)` | 불가 | 없음 |
| `description` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `deleted_at` | `TIMESTAMPTZ` | 가능 | `NULL` |

### FK

```sql
FOREIGN KEY (user_id)
REFERENCES users(id)
ON DELETE RESTRICT
```

### 제약과 인덱스

```sql
CHECK (length(btrim(name)) > 0)
```

```sql
CREATE UNIQUE INDEX uq_models_active_user_name
ON models (user_id, lower(btrim(name)))
WHERE deleted_at IS NULL;
```

```sql
CREATE INDEX idx_models_user
ON models (user_id);
```

### 신규 모델 생성

신규 Model 요청은 같은 트랜잭션에서 Model, 최초 TrainingJob, OutboxEvent를 생성한다.

Model에는 TRAINING 또는 READY 상태를 저장하지 않는다.

Model soft delete를 위해 모든 ModelVersion을 ARCHIVED할 필요는 없다. 다만 `status != DELETED` InferenceDeployment가 해당 Model의 ModelVersion을 참조하면 soft delete를 거부한다. soft-deleted Model의 READY ModelVersion은 남을 수 있지만 신규 InferenceDeployment 생성에는 사용할 수 없다.

---

## 5.7 `training_jobs`

### 역할

특정 READY DatasetVersion으로 대상 Model의 새 버전을 생성하는 학습 실행이다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `user_id` | `UUID` | 불가 | 없음 |
| `model_id` | `UUID` | 불가 | 없음 |
| `dataset_version_id` | `UUID` | 불가 | 없음 |
| `target_column_id` | `UUID` | 불가 | 없음 |
| `status` | `VARCHAR(32)` | 불가 | `'QUEUED'` |
| `algorithm` | `VARCHAR(100)` | 불가 | 없음 |
| `hyperparameters` | `JSONB` | 불가 | `'{}'::jsonb` |
| `requested_gpu_count` | `INTEGER` | 불가 | `1` |
| `idempotency_key` | `VARCHAR(255)` | 불가 | 없음 |
| `mlflow_run_id` | `VARCHAR(255)` | 가능 | `NULL` |
| `started_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `finished_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `cancel_requested_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `error_message` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (user_id)
REFERENCES users(id)
ON DELETE RESTRICT
```

```sql
FOREIGN KEY (model_id)
REFERENCES models(id)
ON DELETE RESTRICT
```

```sql
FOREIGN KEY (dataset_version_id)
REFERENCES dataset_versions(id)
ON DELETE RESTRICT
```

```sql
FOREIGN KEY (target_column_id)
REFERENCES dataset_columns(id)
ON DELETE RESTRICT
```

`idx_training_jobs_target_column` 인덱스를 사용한다. 서비스 계층은 target의 dataset_version_id가 TrainingJob.dataset_version_id와 같은지 검증한다.

### 상태

```text
QUEUED
→ SCHEDULING
→ RUNNING
→ SUCCEEDED | FAILED

QUEUED | SCHEDULING | RUNNING
→ CANCEL_REQUESTED
→ CANCELLED
```

`SCHEDULING`에서도 취소를 허용한다. Training Controller는 Kubernetes Job 생성 전에는 생성을 중단하고, 생성 직후 취소 요청을 확인한 경우 최신 Kubernetes Job 상태를 먼저 조회한다. Complete 또는 Failed면 해당 terminal 처리 규칙을 적용하고 terminal 상태가 아니면 Job을 삭제한다.

### Check Constraint

```sql
CHECK (
  status IN (
    'QUEUED','SCHEDULING','RUNNING','SUCCEEDED',
    'FAILED','CANCEL_REQUESTED','CANCELLED'
  )
)
CHECK (requested_gpu_count > 0)
CHECK (length(btrim(algorithm)) > 0)
CHECK (length(btrim(idempotency_key)) > 0)
CHECK (finished_at IS NULL OR started_at IS NOT NULL)
CHECK (finished_at IS NULL OR finished_at >= started_at)
CHECK (
  cancel_requested_at IS NULL
  OR cancel_requested_at >= created_at
)
```

### Unique

```sql
UNIQUE (user_id, idempotency_key)
```

### 인덱스

```sql
CREATE INDEX idx_training_jobs_user_created
ON training_jobs (user_id, created_at DESC);
```

```sql
CREATE INDEX idx_training_jobs_status_created
ON training_jobs (status, created_at);
```

```sql
CREATE INDEX idx_training_jobs_model_created
ON training_jobs (model_id, created_at DESC);
```

```sql
CREATE INDEX idx_training_jobs_dataset_version
ON training_jobs (dataset_version_id);
```

### 서비스 계층 검증

TrainingJob 생성 트랜잭션에서:

- DatasetVersion 존재
- Dataset 및 Model 소유권
- Dataset/Model 미삭제
- DatasetVersion `READY`
- target column 존재·같은 DatasetVersion·UNKNOWN 제외, Algorithm Registry의 target/feature 타입 호환성, usable feature 1개 이상
- GPU quota
- `TrainingJob.user_id = Model.user_id = Dataset.user_id`

DatasetVersion은 `FOR SHARE`로 조회한다.

GPU quota의 API 검증은 best-effort이며, Training Controller가 scheduling 직전에 authoritative 재검증한다. scheduling deadline은 기본 72시간 운영 설정으로 `created_at`과 설정값에서 계산하며 별도 컬럼을 추가하지 않는다.

멱등 비교 핵심 필드에는 target_column_id를 포함한다. 알려진 미지원 feature type은 제외하지 않고 `UNSUPPORTED_FEATURE_COLUMN_TYPE`으로 거부하며 UNKNOWN만 정책적으로 제외한다.

---

## 5.8 `training_job_events`

### 역할

TrainingJob 내부 상태 전이와 실행 이벤트의 append-only 이력이다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `training_job_id` | `UUID` | 불가 | 없음 |
| `event_type` | `VARCHAR(100)` | 불가 | 없음 |
| `from_status` | `VARCHAR(32)` | 가능 | `NULL` |
| `to_status` | `VARCHAR(32)` | 가능 | `NULL` |
| `message` | `TEXT` | 가능 | `NULL` |
| `metadata_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `occurred_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (training_job_id)
REFERENCES training_jobs(id)
ON DELETE CASCADE
```

### Check Constraint

```sql
CHECK (length(btrim(event_type)) > 0)
CHECK (
  from_status IS NULL OR from_status IN (
    'QUEUED','SCHEDULING','RUNNING','SUCCEEDED',
    'FAILED','CANCEL_REQUESTED','CANCELLED'
  )
)
CHECK (
  to_status IS NULL OR to_status IN (
    'QUEUED','SCHEDULING','RUNNING','SUCCEEDED',
    'FAILED','CANCEL_REQUESTED','CANCELLED'
  )
)
```

### 인덱스

```sql
CREATE INDEX idx_training_job_events_job_occurred
ON training_job_events (training_job_id, occurred_at, id);
```

`sequence_number`는 두지 않는다. 정렬은 `(occurred_at, id)`를 사용한다.

`event_type`은 자유 문자열이므로 새 실행 이벤트를 위해 스키마를 변경하지 않는다. 상태 유지 실행 이벤트의 예시는 `QUOTA_WAITING`, `ORPHAN_JOB_DETECTED`, `POD_RETRY_SCHEDULED`, `CHECKPOINT_CREATED`, `CHECKPOINT_INVALIDATED`, `CHECKPOINT_RESUMED`, `TRAINING_RESTARTED`, `CANDIDATE_TRAINING_FAILED`, `MODEL_VERSION_CREATING`, `MODEL_ARTIFACT_PUBLISHED`, `MODEL_VERSION_READY`, `MODEL_VERSION_FAILED`, `TRAINING_RESULT_FINALIZATION_STARTED`이며 이 경우에만 `from_status`는 현재 상태, `to_status`는 NULL이다. `CANDIDATE_TRAINING_FAILED`는 ModelVersion row 생성 전 후보 실패이며 metadata의 candidate_number, error_code, stage가 필수다. 최종 후보 집계에서는 이벤트 행 수 대신 distinct candidate_number를 사용하고, 같은 candidate에 ModelVersion row가 있으면 ModelVersion을 authoritative 결과로 사용해 이벤트를 이중 집계하지 않는다. `MODEL_VERSION_FAILED`는 CREATING 생성 후 publish 실패다. `TRAINING_RESULT_FINALIZATION_STARTED`는 가장 이른 `(occurred_at, id)`를 결과 확정 대기 시작점으로 사용하며 단일 Controller는 재삽입하지 않고 다중 Controller의 관측 중복은 허용한다. 상태 전이를 동반하는 실패 이벤트 또는 오류 코드의 예시는 `GPU_QUOTA_WAIT_TIMEOUT`, `SCHEDULING_TIMEOUT`, `KUBERNETES_JOB_LOST`, `TRAINING_DEADLINE_EXCEEDED`, `TRAINING_RESULT_INCOMPLETE`, `ALL_MODEL_CANDIDATES_FAILED`, `NO_MODEL_CANDIDATE_PRODUCED`이다. UUID `id`는 생성 순서가 아니라 `occurred_at` 동률의 결정적 타이브레이커다. `metadata_json`은 내부 운영 원본이며 외부 API는 allowlist projection만 반환한다.

---

## 5.9 `training_checkpoints`

### 역할

S3 Checkpoint 객체의 메타데이터다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `training_job_id` | `UUID` | 불가 | 없음 |
| `sequence_number` | `INTEGER` | 불가 | 없음 |
| `epoch` | `BIGINT` | 가능 | `NULL` |
| `step` | `BIGINT` | 가능 | `NULL` |
| `storage_uri` | `TEXT` | 불가 | 없음 |
| `size_bytes` | `BIGINT` | 가능 | `NULL` |
| `checksum_algorithm` | `VARCHAR(16)` | 불가 | `'SHA256'` |
| `checksum` | `VARCHAR(128)` | 가능 | `NULL` |
| `is_resumable` | `BOOLEAN` | 불가 | `true` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (training_job_id)
REFERENCES training_jobs(id)
ON DELETE CASCADE
```

### Check Constraint

```sql
CHECK (sequence_number > 0)
CHECK (epoch IS NULL OR epoch >= 0)
CHECK (step IS NULL OR step >= 0)
CHECK (size_bytes IS NULL OR size_bytes >= 0)
CHECK (checksum_algorithm = 'SHA256')
CHECK (length(btrim(storage_uri)) > 0)
```

### Unique

```sql
UNIQUE (training_job_id, sequence_number)
```

TrainingCheckpoint row는 resume 후보의 publish marker다. checkpoint_id는 별도 컬럼이 아니라 S3 publish 전에 애플리케이션이 사전 생성해 명시적으로 INSERT하는 `TrainingCheckpoint.id`다. `storage_uri`는 `s3://<bucket>/checkpoints/{training_job_id}/{checkpoint_id}/` 형식의 checkpoint_id 기반 final immutable URI다. TrainingJob 행을 `FOR UPDATE`로 잠근 뒤 S3 최종 객체 검증 후 `id=checkpoint_id`를 재조회하고, row가 없을 때만 `MAX(sequence_number) + 1`을 할당한다. 동일 row의 training_job_id·storage_uri·size·checksum·epoch·step이 같으면 멱등 성공이며 새 sequence를 할당하지 않는다. INSERT PK 충돌은 rollback·id 재조회로 처리하고, metadata가 다르면 `CHECKPOINT_ID_CONFLICT`, row가 없으면 제한된 재시도 또는 정합성 오류다. sequence_number는 DB 정렬·resume 후보 선택 순번일 뿐 S3 object key나 manifest 필수 검증값이 아니다. `is_resumable`은 변경 가능한 유효성 flag이고 무효화 원인·시각은 TrainingJobEvent에 기록한다. resume은 최신 5개 후보까지 검사하며 내부 `storage_uri`는 사용자 API에 직접 노출하지 않는다.

---

## 5.10 `model_versions`

### 역할

특정 TrainingJob에서 생성된 실제 모델 후보와 artifact metadata다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `model_id` | `UUID` | 불가 | 없음 |
| `training_job_id` | `UUID` | 불가 | 없음 |
| `version_number` | `INTEGER` | 불가 | 없음 |
| `candidate_number` | `INTEGER` | 불가 | `1` |
| `status` | `VARCHAR(32)` | 불가 | `'CREATING'` |
| `artifact_uri` | `TEXT` | 가능 | `NULL` |
| `artifact_format` | `VARCHAR(64)` | 가능 | `NULL` |
| `metrics_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `mlflow_run_id` | `VARCHAR(255)` | 가능 | `NULL` |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `error_message` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (model_id)
REFERENCES models(id)
ON DELETE RESTRICT
```

```sql
FOREIGN KEY (training_job_id)
REFERENCES training_jobs(id)
ON DELETE RESTRICT
```

### 상태

```text
CREATING
READY
FAILED
ARCHIVED
```

### Check Constraint

```sql
CHECK (version_number > 0)
CHECK (candidate_number > 0)
CHECK (status IN ('CREATING','READY','FAILED','ARCHIVED'))
CHECK (
  status <> 'READY'
  OR (
    artifact_uri IS NOT NULL
    AND length(btrim(artifact_uri)) > 0
    AND artifact_format IS NOT NULL
    AND length(btrim(artifact_format)) > 0
  )
)
```

### Unique

```sql
UNIQUE (model_id, version_number)
UNIQUE (training_job_id, candidate_number)
```

### 정합성

```text
ModelVersion.model_id = TrainingJob.model_id
```

ModelVersion 생성 시 `model_id`를 외부 입력으로 받지 않고 TrainingJob에서 복사한다.

대표 후보/default version은 초기 범위에서 지정하지 않는다. InferenceDeployment가 배포할 ModelVersion을 직접 참조한다.

`candidate_number`는 TrainingJob 내부에서 후보 설정·학습 계획 생성 시 결정하는 1부터 시작하는 순번이다. 완료 순서나 성능 순위가 아니며 Pod retry는 동일 `(training_job_id, candidate_number)`와 기존 `model_version_id`를 재사용한다. 후보 학습·평가, 로컬 artifact 직렬화, ModelInterface 로컬 검증이 끝나면 staging 업로드 전에 최초 CREATING row와 새 UUID를 만든다. 직렬화·로컬 ModelInterface 생성·검증 오류에는 ModelVersion row가 없고 `CANDIDATE_TRAINING_FAILED` 이벤트만 기록한다. CREATING 생성 후 publish 오류만 ModelVersion.error_code와 `MODEL_VERSION_FAILED` 이벤트로 기록한다. `FAILED` row는 재생성하지 않는다.

READY → ARCHIVED 요청은 `status != DELETED` InferenceDeployment가 해당 ModelVersion을 하나라도 참조하면 `409 MODEL_VERSION_IN_USE`로 거부한다. ARCHIVED → READY 복원은 초기 범위에서 금지한다.

`version_number`는 Model 내부 공개 버전 순번이다. Model 부모 행을 `FOR UPDATE`로 잠근 뒤 `MAX(version_number) + 1`로 할당하며, FAILED ModelVersion도 번호를 소비할 수 있고 gap은 허용한다.

`READY` publish marker는 `status=READY`와 정확히 하나의 ModelInterface 존재다. READY row는 `artifact_uri`·`artifact_format` 존재뿐 아니라 final artifact·manifest 검증, ModelInterface 검증, `ModelVersion.model_id = TrainingJob.model_id`를 만족해야 한다. checksum의 초기 기준 저장소는 S3 manifest이며 DB 컬럼을 추가하지 않는다. artifact URI와 S3 위치는 사용자 API 기본 응답에서 비노출한다.

ModelVersion 상태 변경 주체는 실행 중 publish의 Training Job, Kubernetes Job 종료 뒤 reconciliation·30분 CREATING timeout을 처리하는 Training Controller/Reconciler, 그리고 ARCHIVED 요청의 Backend API다. TrainingJob이 `TRAINING_RESULT_INCOMPLETE`로 FAILED되면 잔존 CREATING row는 같은 reconciliation 과정에서 `TRAINING_RESULT_FINALIZATION_TIMEOUT`으로 FAILED 처리하며 이후 READY 전이를 허용하지 않는다. 취소로 staging 검증 전 publish를 중단할 때는 `MODEL_PUBLISH_CANCELLED`를 사용한다. 이 오류 코드는 자유 문자열이므로 스키마 변경이 필요 없다.

최초 CREATING INSERT가 `UNIQUE(training_job_id, candidate_number)` 충돌을 내면 트랜잭션을 rollback한 뒤 기존 candidate row를 재조회한다. CREATING이면 기존 `model_version_id`·`version_number`를 재사용하고, READY면 멱등 성공, FAILED면 중단, ARCHIVED나 row 부재면 정합성 오류 또는 제한된 재시도로 처리한다. 재조회 뒤 새 UUID나 version_number를 다시 할당하지 않는다.

---

## 5.11 `model_interfaces`

### 역할

ModelVersion의 입력·출력 JSON Schema 계약이다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `model_version_id` | `UUID` | 불가 | 없음 |
| `input_schema_json` | `JSONB` | 불가 | 없음 |
| `output_schema_json` | `JSONB` | 불가 | 없음 |
| `schema_version` | `VARCHAR(32)` | 불가 | `'1.0'` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (model_version_id)
REFERENCES model_versions(id)
ON DELETE CASCADE
```

### 제약

```sql
UNIQUE (model_version_id)
CHECK (length(btrim(schema_version)) > 0)
```

JSONB 문법은 DB가 보장하고 JSON Schema 표준 유효성은 애플리케이션이 검증한다.

ModelInterface는 ModelVersion READY finalization과 같은 DB 트랜잭션에서 생성 또는 기존 값 검증을 수행한다. `UNIQUE(model_version_id)` 충돌 시 input/output/schema_version이 모두 같으면 멱등 성공이고, 다르면 `MODEL_INTERFACE_CONFLICT`로 ModelVersion을 FAILED 처리한다.

---

## 5.12 `inference_deployments`

### 역할

특정 ModelVersion을 KServe로 실행하는 사용자 소유 배포 리소스다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `user_id` | `UUID` | 불가 | 없음 |
| `model_version_id` | `UUID` | 불가 | 없음 |
| `name` | `VARCHAR(255)` | 불가 | 없음 |
| `environment` | `VARCHAR(16)` | 불가 | 없음 |
| `status` | `VARCHAR(32)` | 불가 | `'PENDING'` |
| `kserve_namespace` | `VARCHAR(253)` | 가능 | `NULL` |
| `kserve_service_name` | `VARCHAR(253)` | 가능 | `NULL` |
| `endpoint` | `TEXT` | 가능 | `NULL` |
| `min_replicas` | `INTEGER` | 불가 | `1` |
| `max_replicas` | `INTEGER` | 불가 | `1` |
| `traffic_config_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `operation_started_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `applied_min_replicas` | `INTEGER` | 가능 | `NULL` |
| `applied_max_replicas` | `INTEGER` | 가능 | `NULL` |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `error_message` | `TEXT` | 가능 | `NULL` |
| `created_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `updated_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (user_id)
REFERENCES users(id)
ON DELETE RESTRICT
```

```sql
FOREIGN KEY (model_version_id)
REFERENCES model_versions(id)
ON DELETE RESTRICT
```

### 서비스 계층 검증과 불변조건

InferenceDeployment는 하나의 특정 ModelVersion에 고정된 배포 리소스다. `model_version_id`는 생성 후 변경할 수 없으며, 다른 ModelVersion을 serving하려면 새 InferenceDeployment를 생성한다. model_version_id PATCH, in-place replacement, stable alias 또는 traffic split을 통한 version 전환은 초기 범위에서 지원하지 않는다.

생성 시 서비스 계층은 참조 ModelVersion 존재·`READY` 상태, 상위 Model 존재·`deleted_at IS NULL`, 그리고 `InferenceDeployment.user_id = ModelVersion → Model.user_id`를 검증한다. user_id는 요청 본문이 아니라 인증된 요청 context에서 주입한다. `CREATING`, `FAILED`, `ARCHIVED` ModelVersion과 soft-deleted Model의 READY ModelVersion은 신규 Deployment에 사용할 수 없다.

### 상태와 환경

min_replicas/max_replicas는 desired configuration이고 applied_*는 마지막 KServe Ready 검증값이다. operation_started_at은 DEPLOYING/UPDATING/DELETING timeout 기준이다. endpoint는 관측 metadata이며 Gateway routing 기준은 kserve_namespace와 kserve_service_name이다. traffic_config_json은 초기 `{}`로 고정한다.

| 상태 | `endpoint` |
|---|---|
| `PENDING` | `NULL` |
| `DEPLOYING` | `NULL` |
| `READY` | Controller가 관측한 내부 serving endpoint |
| `UPDATING` | 기존 service가 serving 가능한 동안 기존 endpoint 유지 |
| `FAILED` | `NULL` |
| `DELETING` | `NULL` |
| `DELETED` | `NULL` |

`PENDING → DEPLOYING`과 resource 유실/immutable drift의 `READY → DEPLOYING`은 endpoint를 NULL로 초기화한다. `DEPLOYING → READY`에서 Controller가 관측값을 기록하며, 실패·삭제 상태에서는 NULL로 관리한다. endpoint, kserve_namespace, kserve_service_name은 일반 사용자 API에 노출하지 않는다.

```sql
CHECK (operation_started_at IS NULL OR operation_started_at >= created_at)
CHECK ((applied_min_replicas IS NULL AND applied_max_replicas IS NULL) OR (applied_min_replicas >= 1 AND applied_max_replicas >= applied_min_replicas))
```

```text
status:
PENDING → DEPLOYING → READY
DEPLOYING → FAILED
READY → UPDATING → READY
UPDATING → FAILED (rollback 실패 또는 timeout)
삭제 → DELETING → DELETED
DELETING → FAILED

environment:
DEVELOPMENT
STAGING
PRODUCTION
```

### Check Constraint

```sql
CHECK (length(btrim(name)) > 0)
CHECK (
  environment IN ('DEVELOPMENT','STAGING','PRODUCTION')
)
CHECK (
  status IN (
    'PENDING','DEPLOYING','READY','UPDATING',
    'FAILED','DELETING','DELETED'
  )
)
CHECK (min_replicas >= 1)
CHECK (max_replicas >= min_replicas)
```

`min_replicas >= 1`은 KServe Standard Mode와 Knative scale-to-zero 제외 결정에 따른다.

### Unique와 인덱스

```sql
CREATE UNIQUE INDEX uq_inference_deployments_active_user_env_name
ON inference_deployments (
  user_id,
  environment,
  lower(btrim(name))
)
WHERE status <> 'DELETED';
```

```sql
CREATE UNIQUE INDEX uq_inference_deployments_kserve_resource
ON inference_deployments (
  kserve_namespace,
  kserve_service_name
)
WHERE kserve_namespace IS NOT NULL
  AND kserve_service_name IS NOT NULL
  AND status <> 'DELETED';
```

```sql
CREATE INDEX idx_inference_deployments_user_status
ON inference_deployments (user_id, status, created_at DESC);
```

```sql
CREATE INDEX idx_inference_deployments_model_version
ON inference_deployments (model_version_id);
```

---

## 5.13 `audit_logs`

### 역할

사용자 또는 시스템이 수행한 관리 행위의 append-only 감사 기록이다.

```text
AuditLog
= actor 중심 관리 행위

TrainingJobEvent
= TrainingJob 중심 내부 상태·실행 이벤트
```

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `actor_type` | `VARCHAR(32)` | 불가 | `'USER'` |
| `actor_user_id` | `UUID` | 가능 | `NULL` |
| `action` | `VARCHAR(100)` | 불가 | 없음 |
| `resource_type` | `VARCHAR(64)` | 불가 | 없음 |
| `resource_id` | `UUID` | 가능 | `NULL` |
| `request_id` | `VARCHAR(100)` | 가능 | `NULL` |
| `result` | `VARCHAR(32)` | 불가 | 없음 |
| `error_code` | `VARCHAR(100)` | 가능 | `NULL` |
| `metadata_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `occurred_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### FK

```sql
FOREIGN KEY (actor_user_id)
REFERENCES users(id)
ON DELETE SET NULL
```

`resource_id`는 여러 엔티티를 가리키는 다형적 참조이므로 FK를 두지 않는다.

### Check Constraint

```sql
CHECK (actor_type IN ('USER','SYSTEM'))
CHECK (result IN ('SUCCESS','FAILURE'))
CHECK (length(btrim(action)) > 0)
CHECK (length(btrim(resource_type)) > 0)
```

`actor_type`과 `actor_user_id`의 상관 CHECK는 두지 않는다.

```text
actor_type='USER', actor_user_id=NULL
```

은 원래 사용자 행위였으나 해당 User 레코드가 이후 물리 삭제된 상태를 의미한다.

사용자 이메일 snapshot은 개인정보 보존 정책이 확정되기 전까지 저장하지 않는다.

### 인덱스

```sql
CREATE INDEX idx_audit_logs_resource
ON audit_logs (resource_type, resource_id, occurred_at DESC);
```

```sql
CREATE INDEX idx_audit_logs_actor
ON audit_logs (actor_user_id, occurred_at DESC);
```

```sql
CREATE INDEX idx_audit_logs_request
ON audit_logs (request_id)
WHERE request_id IS NOT NULL;
```

---

## 5.14 `outbox_events`

### 역할

비즈니스 DB 변경과 SQS 발행의 이중 쓰기 불일치를 방지한다.

### 컬럼

| 컬럼 | 타입 | NULL | 기본값 |
|---|---|---:|---|
| `id` | `UUID` | 불가 | `gen_random_uuid()` |
| `aggregate_type` | `VARCHAR(64)` | 불가 | 없음 |
| `aggregate_id` | `UUID` | 불가 | 없음 |
| `event_type` | `VARCHAR(100)` | 불가 | 없음 |
| `payload_json` | `JSONB` | 불가 | `'{}'::jsonb` |
| `idempotency_key` | `VARCHAR(255)` | 가능 | `NULL` |
| `occurred_at` | `TIMESTAMPTZ` | 불가 | `now()` |
| `published_at` | `TIMESTAMPTZ` | 가능 | `NULL` |
| `retry_count` | `INTEGER` | 불가 | `0` |
| `last_error` | `TEXT` | 가능 | `NULL` |
| `next_attempt_at` | `TIMESTAMPTZ` | 불가 | `now()` |

### 다형적 참조

`aggregate_id`는 DatasetVersion, TrainingJob, InferenceDeployment 등 여러 aggregate를 가리키므로 FK를 두지 않는다.

`idempotency_key`는 API 요청과 OutboxEvent의 감사·추적 연결 metadata다. Consumer 멱등성 판단에는 사용하지 않는다.

### Check Constraint

```sql
CHECK (retry_count >= 0)
CHECK (length(btrim(aggregate_type)) > 0)
CHECK (length(btrim(event_type)) > 0)
CHECK (
  published_at IS NULL
  OR published_at >= occurred_at
)
```

### Pending 인덱스

```sql
CREATE INDEX idx_outbox_events_pending
ON outbox_events (next_attempt_at, occurred_at)
WHERE published_at IS NULL;
```

### Publisher 조회

```sql
SELECT *
FROM outbox_events
WHERE published_at IS NULL
  AND next_attempt_at <= now()
ORDER BY next_attempt_at, occurred_at
FOR UPDATE SKIP LOCKED
LIMIT :batch_size;
```

### 재시도와 보존

- 실패: `retry_count + 1`, `last_error`, 지수 백오프 기반 `next_attempt_at`
- 성공: `published_at = now()`
- 발행 완료 이벤트: 30일 보존 후 batch 삭제
- 미발행 이벤트: 자동 삭제 금지

---

# 6. 버전 번호 동시성

대상:

- `dataset_versions.version_number`
- `model_versions.version_number`

처리:

```text
1. 부모 Dataset 또는 Model 행 SELECT ... FOR UPDATE
2. MAX(version_number) + 1 계산
3. 자식 INSERT
4. UNIQUE(parent_id, version_number)로 최종 방어
```

Advisory Lock은 사용하지 않는다.

---

# 7. Dataset Aggregate 조회

Dataset 테이블에 최신 버전 메타데이터를 중복 저장하지 않는다.

## 정의

```text
latest_version
= 상태와 관계없이 version_number 최대

latest_ready_version
= READY 상태 중 version_number 최대
```

## 목록 응답

최신 진행 상태 요약을 제공할 수 있다.

```json
{
  "id": "dataset-id",
  "name": "customer-churn",
  "latest_version_number": 3,
  "latest_version_status": "PROCESSING"
}
```

## 상세 응답

```json
{
  "id": "dataset-id",
  "name": "customer-churn",
  "latest_version": {
    "version_number": 3,
    "status": "PROCESSING"
  },
  "latest_ready_version": {
    "version_number": 2,
    "status": "READY"
  }
}
```

## 쿼리 패턴

```sql
LEFT JOIN LATERAL (
  SELECT dv.*
  FROM dataset_versions dv
  WHERE dv.dataset_id = d.id
  ORDER BY dv.version_number DESC
  LIMIT 1
) latest_version ON true
```

```sql
LEFT JOIN LATERAL (
  SELECT dv.*
  FROM dataset_versions dv
  WHERE dv.dataset_id = d.id
    AND dv.status = 'READY'
  ORDER BY dv.version_number DESC
  LIMIT 1
) latest_ready_version ON true
```

---

# 8. Soft Delete와 물리 삭제

## Soft Delete 대상

- Dataset
- Model

```sql
deleted_at TIMESTAMPTZ NULL
```

복원 기간은 30일이다.

## Dataset 물리 삭제

```text
1. 30일 경과 확인
2. S3 원본·처리본 삭제
3. S3 삭제 성공
4. Dataset DELETE
5. DatasetVersion, DatasetColumn, UploadSession CASCADE
```

TrainingJob이 DatasetVersion을 참조하면 RESTRICT로 전체 DELETE가 실패한다. 학습 재현성을 위해 정상 동작이다.

## Model 물리 삭제

ModelVersion, TrainingJob, InferenceDeployment가 RESTRICT하므로 provenance 또는 배포가 남아 있으면 물리 삭제를 허용하지 않는다.

---

# 9. 상태 변경 주체

| 엔티티 | 상태 변경 주체 |
|---|---|
| DatasetVersion | Backend API, Dataset Processing Job/Controller |
| UploadSession | Backend API, Cleanup Job |
| TrainingJob | Backend API의 취소 요청, Training Controller |
| ModelVersion | Training Job, Training Controller/Reconciler, Backend API의 비활성화 요청 |
| InferenceDeployment | Backend API, Deployment Controller |

외부 사용자가 임의의 상태 PATCH를 수행하는 API는 제공하지 않는다.

---

# 10. 구현 범위와 운영 설계

## P0

- User seed
- Dataset CRUD
- PostgreSQL
- Alembic
- Docker Compose
- Health Check
- 테스트
- README

Dataset은 논리 리소스 구조를 유지한다. 평가 편의를 위해 파일 metadata를 Dataset 테이블에 비정규화하지 않는다.

## P1

- DatasetVersion 생성·조회
- Dataset aggregate 응답
- 상태 및 제약

## P2

- Model + 최초 TrainingJob 원자적 생성
- 기존 Model 재학습
- TrainingJob 조회·취소
- Outbox metadata와 멱등성

## 운영 설계 전용 가능

- 실제 S3 Multipart Upload
- SQS Publisher/Consumer
- Kubernetes Job
- KServe
- Karpenter
- MLflow
- Athena/Glue
- External Secrets Operator
