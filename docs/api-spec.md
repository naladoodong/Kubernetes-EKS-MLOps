# ArgMax Mini Dataset API 명세

- 문서 상태: 구현 전 계약 확정안
- API 버전: `v1`
- Base Path: `/api/v1`
- 구현 범위: Dataset CRUD 4개 API
- 기준 문서: `architecture/architecture-decisions-v3.md`, `architecture/data-model-v5.md`, `architecture/erd-v3.md`, `architecture/system-context-v3.md`, `../database/schema-v2.sql`, Alembic `0001`·`0002`

---

## 1. 목적과 범위

이 문서는 ArgMax Mini 구현 파트에서 제공할 Dataset API의 외부 계약을 정의한다. 전체 MLOps 플랫폼은 설계 대상으로 유지하고, 실제 구현은 다음 4개 비즈니스 API로 제한한다.

| 작업 | Method | Path | 설명 |
|---|---|---|---|
| Create | `POST` | `/api/v1/datasets` | Dataset 생성 |
| Read | `GET` | `/api/v1/datasets/{dataset_id}` | Dataset과 최신 DatasetVersion 요약 조회 |
| Update | `PATCH` | `/api/v1/datasets/{dataset_id}` | Dataset 부분 수정 |
| Delete | `DELETE` | `/api/v1/datasets/{dataset_id}` | Dataset Soft Delete |

Read API는 `Dataset`과 `DatasetVersion`의 1:N 관계를 사용하는 다중 엔티티 API다. `latest_version`과 `latest_ready_version`은 Dataset 테이블에 중복 저장하지 않고 조회 시 조합한다.

### 1.1 구현 제외 범위

- Dataset 목록 API
- DatasetVersion 생성·수정·삭제 API
- 실제 파일 업로드와 S3 또는 MinIO 연동
- TrainingJob, Model, InferenceDeployment API
- SQS, Transactional Outbox Publisher, Kubernetes Job
- MLflow, KServe
- 인증·인가 시스템
- 삭제 Dataset 복원 API
- AuditLog 조회 API

---

## 2. 공통 계약

### 2.1 콘텐츠 형식

- 요청 본문: `application/json`
- 응답 본문: `application/json` (`204 No Content` 제외)
- 시간: UTC 기준 ISO 8601 문자열
- 식별자: UUID 문자열

시간 예:

```text
2026-08-07T08:30:15.123456Z
```

### 2.2 평가 사용자 컨텍스트

인증 구현은 과제 범위에서 제외한다. 모든 Dataset 요청은 다음 고정 평가 사용자의 요청으로 처리한다.

| 항목 | 값 |
|---|---|
| `user_id` | `00000000-0000-4000-8000-000000000001` |
| `email` | `evaluator@argmax-mini.local` |

- `user_id`는 요청 본문이나 헤더로 받지 않는다.
- Dataset 생성 시 고정 `user_id`를 저장한다.
- 조회·수정·삭제는 항상 `dataset.user_id = evaluator_user_id` 조건을 적용한다.
- 다른 사용자의 Dataset 존재 여부는 노출하지 않고 `404 Not Found`로 응답한다.

### 2.3 Request ID

서버는 모든 HTTP 요청마다 UUID 형식의 `request_id`를 새로 생성한다.

```text
요청 수신
→ request_id 생성
→ request.state.request_id 저장
→ Router → Service → AuditLog 및 구조화 로그로 전달
→ X-Request-ID 응답 헤더 반환
```

- 외부에서 받은 `X-Request-ID`는 신뢰하거나 내부 식별자로 재사용하지 않는다.
- 정상 응답과 오류 응답 모두 `X-Request-ID` 헤더를 포함한다.
- 오류 응답 본문의 `request_id`와 응답 헤더 값은 동일하다.

응답 헤더 예:

```http
X-Request-ID: 7eb25f9e-bf4a-44e8-a5cc-87eaa2646412
```

### 2.4 Dataset 이름 규칙

- JSON 타입은 문자열이다.
- API에서 앞뒤 공백을 제거한 후 검증하고 저장한다.
- 공백 제거 후 길이는 `1..255`자다.
- 활성 Dataset 이름은 평가 사용자 범위에서 대소문자와 앞뒤 공백을 무시하고 유일해야 한다.
- 삭제된 Dataset의 이름은 재사용할 수 있다.

다음 값은 같은 활성 이름으로 취급한다.

```text
customer-churn
Customer-Churn
  customer-churn  
```

### 2.5 `description` 규칙

- 문자열 또는 `null`이다.
- DB의 `TEXT` 컬럼과 일치하도록 API 고유의 임의 길이 제한은 두지 않는다.
- 빈 문자열을 허용하며 `null`과 서로 다른 값으로 취급한다.
- 입력 내용을 임의로 trim하지 않는다.

### 2.6 알 수 없는 필드

요청 스키마에 정의되지 않은 필드가 있으면 `422 Unprocessable Entity`로 거부한다.

### 2.7 Soft Delete

- DELETE는 물리 삭제가 아니라 `deleted_at`을 현재 시각으로 설정한다.
- 삭제된 Dataset은 GET, PATCH, DELETE 대상에서 제외한다.
- 삭제된 Dataset을 다시 GET, PATCH 또는 DELETE하면 `404 Not Found`다.
- DELETE 성공 직후 같은 이름으로 새 Dataset을 생성할 수 있다.
- 복원과 30일 후 물리 삭제는 이번 API 구현 범위가 아니다.

---

## 3. 공통 스키마

### 3.1 `DatasetResponse`

| 필드 | 타입 | Nullable | 설명 |
|---|---|---:|---|
| `id` | UUID string | 아니요 | Dataset ID |
| `name` | string | 아니요 | 정규화 후 저장된 이름 |
| `description` | string | 예 | 설명 |
| `created_at` | date-time string | 아니요 | 생성 시각 |
| `updated_at` | date-time string | 아니요 | 마지막 수정 시각 |

`user_id`와 `deleted_at`은 내부 소유권·삭제 관리 필드이므로 정상 응답에 노출하지 않는다.

```json
{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn",
  "description": "Customer churn training dataset",
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T08:30:15.123456Z"
}
```

### 3.2 `DatasetVersionSummary`

| 필드 | 타입 | Nullable | 설명 |
|---|---|---:|---|
| `version_number` | integer | 아니요 | Dataset 내부의 양의 버전 순번 |
| `status` | enum | 아니요 | DatasetVersion 처리 상태 |

허용 상태:

```text
PENDING | UPLOADING | UPLOADED | PROCESSING | READY | FAILED
```

### 3.3 `DatasetDetailResponse`

`DatasetResponse`의 모든 필드에 다음 두 필드를 추가한다.

| 필드 | 타입 | Nullable | 정의 |
|---|---|---:|---|
| `latest_version` | `DatasetVersionSummary` | 예 | 상태와 관계없이 `version_number`가 가장 큰 버전 |
| `latest_ready_version` | `DatasetVersionSummary` | 예 | `READY` 상태 중 `version_number`가 가장 큰 버전 |

- DatasetVersion이 없으면 두 필드 모두 `null`이다.
- DatasetVersion은 있지만 READY 버전이 없으면 `latest_ready_version`만 `null`이다.
- 최신 버전이 READY가 아니어도 이전 READY 버전을 별도로 반환한다.

```json
{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn",
  "description": "Customer churn training dataset",
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T08:30:15.123456Z",
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

### 3.4 `ErrorResponse`

모든 오류는 같은 최상위 구조를 사용한다.

| 필드 | 타입 | Nullable | 설명 |
|---|---|---:|---|
| `error.code` | string | 아니요 | 애플리케이션 오류 코드 |
| `error.message` | string | 아니요 | 사람이 읽을 수 있는 요약 |
| `error.details` | array | 아니요 | 상세 오류 목록, 없으면 빈 배열 |
| `request_id` | UUID string | 아니요 | 요청 추적 ID |

```json
{
  "error": {
    "code": "DATASET_NOT_FOUND",
    "message": "Dataset was not found.",
    "details": []
  },
  "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412"
}
```

검증 오류의 `details` 항목:

| 필드 | 타입 | 설명 |
|---|---|---|
| `field` | string | 오류 위치. 예: `body.name`, `path.dataset_id` |
| `reason` | string | 검증 실패 이유 |

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "body.name",
        "reason": "String must contain at least 1 character after trimming."
      }
    ]
  },
  "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412"
}
```

오류 응답에는 내부 SQL, stack trace, 파일 경로 또는 비밀정보를 포함하지 않는다.

### 3.5 오류 코드와 상태 코드

| HTTP 상태 | 오류 코드 | 조건 |
|---:|---|---|
| `404` | `DATASET_NOT_FOUND` | Dataset이 없거나, 삭제됐거나, 평가 사용자 소유가 아님 |
| `409` | `DATASET_NAME_CONFLICT` | 같은 정규화 이름의 활성 Dataset이 이미 존재 |
| `422` | `VALIDATION_ERROR` | 본문·경로 파라미터·JSON 형식 검증 실패 |
| `500` | `INTERNAL_ERROR` | 예상하지 못한 서버 오류 |

DB의 `uq_datasets_active_user_name` 위반 중 알려진 Dataset 이름 충돌만 `409`로 변환한다. 그 외 무결성 오류를 포괄적으로 `409`로 변환하지 않는다.

---

## 4. Dataset 생성

### `POST /api/v1/datasets`

활성 Dataset을 생성한다.

### 4.1 요청 본문: `DatasetCreateRequest`

| 필드 | 타입 | 필수 | Nullable | 규칙 |
|---|---|---:|---:|---|
| `name` | string | 예 | 아니요 | trim 후 `1..255`자 |
| `description` | string | 아니요 | 예 | 생략 시 `null` |

```http
POST /api/v1/datasets HTTP/1.1
Content-Type: application/json

{
  "name": "  customer-churn  ",
  "description": "Customer churn training dataset"
}
```

### 4.2 성공 응답

- 상태: `201 Created`
- 본문: `DatasetResponse`
- `Location`: 생성된 리소스의 상대 URI
- `X-Request-ID`: 서버 생성 요청 ID

```http
HTTP/1.1 201 Created
Location: /api/v1/datasets/0a89cb0c-c78b-4c68-9f41-3f3fa7238131
X-Request-ID: 7eb25f9e-bf4a-44e8-a5cc-87eaa2646412
Content-Type: application/json

{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn",
  "description": "Customer churn training dataset",
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T08:30:15.123456Z"
}
```

### 4.3 오류 응답

| 상태 | 코드 | 조건 |
|---:|---|---|
| `409` | `DATASET_NAME_CONFLICT` | 활성 Dataset 이름 중복 |
| `422` | `VALIDATION_ERROR` | 이름 누락·빈 이름·255자 초과·타입 오류·잘못된 JSON·알 수 없는 필드 |
| `500` | `INTERNAL_ERROR` | 예상하지 못한 오류 |

---

## 5. Dataset 상세 조회

### `GET /api/v1/datasets/{dataset_id}`

Dataset과 최신 DatasetVersion 요약을 조회한다.

### 5.1 경로 파라미터

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `dataset_id` | UUID string | 예 | 조회할 Dataset ID |

### 5.2 성공 응답

- 상태: `200 OK`
- 본문: `DatasetDetailResponse`
- `X-Request-ID`: 서버 생성 요청 ID

```http
HTTP/1.1 200 OK
X-Request-ID: 02ee5f4f-b87f-4f3f-ad3f-7bea817ed989
Content-Type: application/json

{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn",
  "description": "Customer churn training dataset",
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T08:30:15.123456Z",
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

버전이 없는 경우:

```json
{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn",
  "description": null,
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T08:30:15.123456Z",
  "latest_version": null,
  "latest_ready_version": null
}
```

### 5.3 조회 구현 계약

- Dataset과 두 버전 요약을 한 번의 SQL로 조회한다.
- `latest_version`은 상태 필터 없이 `version_number DESC LIMIT 1`로 선택한다.
- `latest_ready_version`은 `status = 'READY'` 조건에서 `version_number DESC LIMIT 1`로 선택한다.
- 두 버전 요약은 가용한 인덱스를 활용할 수 있는 LATERAL JOIN 형태로 조회한다.
  - `latest_version`: `UNIQUE (dataset_id, version_number)`가 생성하는 B-tree 인덱스의 역방향 스캔 후보
  - `latest_ready_version`: `idx_dataset_versions_dataset_status_version (dataset_id, status, version_number DESC)` 인덱스 후보
- 실제 인덱스 선택은 데이터 분포와 PostgreSQL 옵티마이저 판단에 따르므로 특정 실행 계획을 계약으로 보장하지 않는다.
- DatasetVersion 수가 증가해도 추가 쿼리가 발생하지 않아야 한다.

### 5.4 오류 응답

| 상태 | 코드 | 조건 |
|---:|---|---|
| `404` | `DATASET_NOT_FOUND` | Dataset이 없거나, 삭제됐거나, 평가 사용자 소유가 아님 |
| `422` | `VALIDATION_ERROR` | `dataset_id`가 UUID 형식이 아님 |
| `500` | `INTERNAL_ERROR` | 예상하지 못한 오류 |

GET 실패는 FAILURE AuditLog 기록 대상이 아니다.

---

## 6. Dataset 부분 수정

### `PATCH /api/v1/datasets/{dataset_id}`

Dataset의 `name`과 `description`을 부분 수정한다.

### 6.1 경로 파라미터

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `dataset_id` | UUID string | 예 | 수정할 Dataset ID |

### 6.2 요청 본문: `DatasetUpdateRequest`

| 필드 | 타입 | 필수 | Nullable | 규칙 |
|---|---|---:|---:|---|
| `name` | string | 아니요 | 아니요 | 제공 시 trim 후 `1..255`자 |
| `description` | string | 아니요 | 예 | `null`이면 기존 설명 제거 |

- 생략한 필드는 변경하지 않는다.
- `description: null`은 명시적인 값 제거다.
- 빈 객체 `{}`는 변경 대상이 없으므로 `422 Unprocessable Entity`다.
- 성공 시 실제 값의 동일 여부와 관계없이 `updated_at`을 현재 시각으로 갱신한다.

```http
PATCH /api/v1/datasets/0a89cb0c-c78b-4c68-9f41-3f3fa7238131 HTTP/1.1
Content-Type: application/json

{
  "name": "customer-churn-v2",
  "description": null
}
```

### 6.3 성공 응답

- 상태: `200 OK`
- 본문: 수정 후 `DatasetResponse`
- `X-Request-ID`: 서버 생성 요청 ID

```http
HTTP/1.1 200 OK
X-Request-ID: f22d277c-d89d-4e29-8d98-e6937ea9cd75
Content-Type: application/json

{
  "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
  "name": "customer-churn-v2",
  "description": null,
  "created_at": "2026-08-07T08:30:15.123456Z",
  "updated_at": "2026-08-07T09:05:41.889201Z"
}
```

### 6.4 동시성·트랜잭션 계약

- 활성·소유 Dataset을 `SELECT ... FOR UPDATE`로 조회한다.
- 이름 중복의 최종 방어는 `uq_datasets_active_user_name` partial unique index가 담당한다.
- Dataset 수정과 SUCCESS AuditLog 기록을 하나의 DB 트랜잭션에서 처리한다.
- AuditLog 저장 또는 flush가 실패하면 Dataset 수정도 rollback한다.

### 6.5 오류 응답

| 상태 | 코드 | 조건 |
|---:|---|---|
| `404` | `DATASET_NOT_FOUND` | Dataset이 없거나, 삭제됐거나, 평가 사용자 소유가 아님 |
| `409` | `DATASET_NAME_CONFLICT` | 변경할 이름과 같은 활성 Dataset이 존재 |
| `422` | `VALIDATION_ERROR` | 잘못된 UUID·빈 본문·잘못된 필드 값·알 수 없는 필드 |
| `500` | `INTERNAL_ERROR` | 예상하지 못한 오류 |

---

## 7. Dataset 삭제

### `DELETE /api/v1/datasets/{dataset_id}`

Dataset을 Soft Delete한다.

### 7.1 경로 파라미터

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `dataset_id` | UUID string | 예 | 삭제할 Dataset ID |

### 7.2 성공 응답

- 상태: `204 No Content`
- 응답 본문 없음
- `Content-Type` 헤더 없음
- `X-Request-ID`: 서버 생성 요청 ID

```http
HTTP/1.1 204 No Content
X-Request-ID: a9442ac0-5977-4024-a91f-932e74d0ec30
```

### 7.3 동시성·트랜잭션 계약

- 활성·소유 Dataset을 `SELECT ... FOR UPDATE`로 조회한다.
- `deleted_at`을 현재 시각으로 설정한다.
- Dataset Soft Delete와 SUCCESS AuditLog 기록을 하나의 DB 트랜잭션에서 처리한다.
- AuditLog 저장 또는 flush가 실패하면 Soft Delete도 rollback한다.
- 이미 삭제된 Dataset에 대한 반복 DELETE는 `204`가 아니라 `404`다.

### 7.4 오류 응답

| 상태 | 코드 | 조건 |
|---:|---|---|
| `404` | `DATASET_NOT_FOUND` | Dataset이 없거나, 이미 삭제됐거나, 평가 사용자 소유가 아님 |
| `422` | `VALIDATION_ERROR` | `dataset_id`가 UUID 형식이 아님 |
| `500` | `INTERNAL_ERROR` | 예상하지 못한 오류 |

---

## 8. 감사 로그 계약

### 8.1 감사 대상

| Method | Route template | 성공·실패 기록 |
|---|---|---|
| `POST` | `/api/v1/datasets` | 예 |
| `PATCH` | `/api/v1/datasets/{dataset_id}` | 예 |
| `DELETE` | `/api/v1/datasets/{dataset_id}` | 예 |
| `GET` | `/api/v1/datasets/{dataset_id}` | 아니요 |
| `GET` | `/health` | 아니요 |

공통 예외 처리기는 실제 URL 문자열이나 prefix가 아니라 `request.method`와 FastAPI route template의 정확한 조합으로 감사 여부를 판별한다.

```text
AUDITED_ROUTES = {
  (POST,   /api/v1/datasets),
  (PATCH,  /api/v1/datasets/{dataset_id}),
  (DELETE, /api/v1/datasets/{dataset_id})
}
```

존재하지 않는 경로와 감사 대상이 아닌 경로의 실패는 AuditLog를 만들지 않는다.

### 8.2 공통 감사 필드

| 필드 | 값 |
|---|---|
| `actor_type` | `USER` |
| `actor_user_id` | 고정 평가 사용자 UUID |
| `resource_type` | `DATASET` |
| `request_id` | 해당 요청의 서버 생성 request ID |
| `metadata_json` | 아래 최소 메타데이터 계약을 따르는 JSON 객체 |

`metadata_json`에는 외부 관찰 결과인 HTTP 상태만 저장한다.

SUCCESS 예시:

```json
{"http_status": 201}
```

FAILURE 예시:

```json
{"http_status": 409}
```

- `http_status`는 정수이며 실제 응답 상태 코드와 같아야 한다.
- FAILURE 원인은 전용 `error_code` 컬럼에 저장하며 `metadata_json`에 중복 저장하지 않는다.
- 요청 본문 원문, Dataset `name`·`description`, 인증·요청 헤더 및 기타 민감정보는 저장하지 않는다.
- API별 SUCCESS 값은 POST `201`, PATCH `200`, DELETE `204`다.
- FAILURE 값은 실제 반환된 `404`, `409`, `422`, `500` 중 하나다.

### 8.3 Action

| API | `action` |
|---|---|
| POST | `DATASET_CREATE` |
| PATCH | `DATASET_UPDATE` |
| DELETE | `DATASET_DELETE` |

### 8.4 SUCCESS 기록

- `result = SUCCESS`
- `error_code = null`
- `resource_id = Dataset ID`
- 비즈니스 변경과 같은 트랜잭션에서 기록한다.
- Dataset 변경 또는 SUCCESS AuditLog 중 하나라도 실패하면 전체 rollback한다.

```text
Dataset 변경
→ SUCCESS AuditLog INSERT
→ flush
→ commit
```

### 8.5 FAILURE 기록

- 원래 비즈니스 트랜잭션을 rollback한 뒤 새 DB 세션의 별도 best-effort 트랜잭션으로 기록한다.
- FAILURE AuditLog 기록 실패가 원래 API의 상태 코드와 응답 본문을 바꾸지 않는다.
- 실패한 감사 기록은 구조화 경고 로그로 남긴다.
- 서비스 계층에서 중복 기록하지 않고 공통 예외 처리 경로가 한 번만 기록한다.
- `RequestValidationError`, 도메인 예외, 예상하지 못한 예외 처리기가 공통 FAILURE 기록 함수를 사용한다.

| API 실패 | `resource_id` |
|---|---|
| POST 생성 거절 | `null` |
| PATCH/DELETE의 유효한 UUID | 요청의 `dataset_id` |
| PATCH/DELETE의 잘못된 UUID | `null` |

| HTTP 오류 | AuditLog `error_code` |
|---:|---|
| `404` | `DATASET_NOT_FOUND` |
| `409` | `DATASET_NAME_CONFLICT` |
| `422` | `VALIDATION_ERROR` |
| `500` | `INTERNAL_ERROR` |

---

## 9. 트랜잭션 경계

### 9.1 공통 원칙

- PostgreSQL 기본 격리 수준 `READ COMMITTED`를 사용한다.
- POST, PATCH, DELETE는 요청당 하나의 비즈니스 DB 트랜잭션을 사용한다.
- Service 계층이 commit과 rollback 경계를 소유한다.
- Repository는 임의로 commit하지 않는다.
- 예상하지 못한 예외가 발생하면 비즈니스 트랜잭션 전체를 rollback한다.
- FAILURE AuditLog는 rollback 후 별도 best-effort 트랜잭션을 사용한다.

### 9.2 변경 API 처리 순서

```text
요청 검증
→ Dataset 조회·잠금 또는 생성
→ Dataset 변경
→ SUCCESS AuditLog 기록
→ flush
→ commit
```

### 9.3 원자성 검증 기준

다음 시나리오는 통합 테스트로 검증한다.

```text
Dataset 변경 수행
→ SUCCESS AuditLog INSERT 강제 실패
→ API 요청 실패
→ Dataset 변경도 DB에 남지 않음
```

---

## 10. OpenAPI 계약

FastAPI 코드가 실제 OpenAPI 문서의 실행 가능한 단일 원천이다. 각 라우트와 Pydantic 스키마에 다음 내용을 포함한다.

- `summary`, `description`, operation ID
- 요청·성공 응답 예시
- 필드 설명과 validation constraint
- `404`, `409`, `422`, `500` 응답 모델과 예시
- `Location`, `X-Request-ID` 응답 헤더
- PATCH의 생략 필드와 명시적 `null` 의미
- DELETE의 Soft Delete와 빈 응답 의미
- `latest_version`과 `latest_ready_version`의 차이

권장 operation ID:

| API | operation ID |
|---|---|
| POST | `createDataset` |
| GET | `getDataset` |
| PATCH | `updateDataset` |
| DELETE | `deleteDataset` |

FastAPI 기본 `HTTPValidationError` 응답을 그대로 노출하지 않고, 실제 공통 `ErrorResponse` 형식으로 문서화하고 반환한다.

---

## 11. 수용 테스트 기준

### 11.1 Create

- 정상 생성과 `201`, `Location`, `X-Request-ID`
- 이름 trim 후 저장
- 대소문자·앞뒤 공백 기준 중복 `409`
- Soft Delete된 이름 재사용 성공
- 유효성 오류 `422`
- SUCCESS AuditLog 원자적 기록
- 409·422·500 FAILURE AuditLog best-effort 기록

### 11.2 Read

- DatasetVersion이 없을 때 두 aggregate 필드가 `null`
- 최신 버전과 최신 READY 버전이 다를 때 정확한 결과
- READY가 없을 때 `latest_ready_version = null`
- 다른 Dataset의 버전이 섞이지 않음
- 단일 SQL 실행과 N+1 부재
- 대표 fixture 데이터에 대한 `EXPLAIN`으로 두 서브쿼리의 가용 인덱스와 실행 계획 확인
- 삭제·타 사용자·미존재 Dataset `404`
- GET 실패 시 AuditLog 미생성

DatasetVersion 데이터는 별도 생성 API가 없으므로 pytest fixture에서 SQLAlchemy ORM으로 직접 삽입한다.

대표 fixture:

| version_number | status | 기대 역할 |
|---:|---|---|
| `1` | `FAILED` | 과거 실패 버전 |
| `2` | `READY` | `latest_ready_version` |
| `3` | `PROCESSING` | `latest_version` |

### 11.3 Update

- 이름만 수정
- 설명만 수정
- `description = null`로 값 제거
- 생략 필드 유지
- 빈 객체와 `name = null` 거부
- `updated_at` 갱신
- 이름 충돌 `409`
- 행 잠금 사용
- AuditLog 실패 시 Dataset 수정 rollback

### 11.4 Delete

- 정상 Soft Delete와 빈 `204` 응답
- 삭제 후 GET·PATCH·DELETE `404`
- 삭제 후 이름 재사용 가능
- 행 잠금 사용
- AuditLog 실패 시 `deleted_at` rollback

### 11.5 공통

- 모든 응답에 `X-Request-ID`
- 오류 본문의 `request_id`와 헤더 일치
- 외부 `X-Request-ID`를 내부 ID로 재사용하지 않음
- 알 수 없는 요청 필드 `422`
- 내부 예외 정보 비노출
- 감사 대상 route template 정확한 판별
- SUCCESS AuditLog의 `metadata_json.http_status`가 실제 `201`, `200`, `204` 응답과 일치
- FAILURE AuditLog의 `metadata_json.http_status`가 실제 오류 응답과 일치
- FAILURE 원인은 `error_code` 컬럼에만 저장되고 `metadata_json`에 중복되지 않음
- 요청 본문, Dataset 이름·설명, 요청·인증 헤더가 `metadata_json`에 저장되지 않음

---

## 12. 운영용 Health Check

`GET /health`는 Docker Compose의 서비스 준비 상태 확인을 위한 운영 endpoint이며, 과제의 Dataset 비즈니스 API 4개에는 포함하지 않는다.

최소 계약:

```http
GET /health HTTP/1.1
```

```http
HTTP/1.1 200 OK
X-Request-ID: 1e3745c7-e52b-4168-b07e-b87b3924a55f
Content-Type: application/json

{
  "status": "ok"
}
```

- 애플리케이션과 DB 연결이 준비된 경우에만 `200 OK`를 반환한다.
- Health Check 실패는 AuditLog 대상이 아니다.

---

## 13. 구현 후 정합성 검증

구현 완료 후 다음 세 대상을 비교한다.

1. 이 문서의 계약
2. FastAPI가 생성한 `/openapi.json`
3. 통합 테스트에서 관찰한 실제 HTTP 동작

상태 코드, nullable, 기본값, 헤더, 오류 구조 또는 PATCH 의미가 다르면 의도된 변경인지 검토한 후 코드와 문서를 함께 수정한다.
