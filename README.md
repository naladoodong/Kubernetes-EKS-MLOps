# ArgMax Mini — AWS EKS-based MLOps Platform Architecture

> **Architecture Case Study · Target Architecture + Limited API Implementation**
>
> **Role:** System Architecture & Backend Design
>
> **Portfolio:** `https://naladoodong.github.io/Kubernetes-EKS-MLOps/`

The portfolio source is isolated in [`portfolio/`](portfolio/) and deploys through a dedicated GitHub Pages workflow. It presents the target EKS architecture and the repository-backed implementation scope as separate claims.

ArgMax Mini의 설계 및 구현 산출물을 통합한 repository입니다. Kubernetes/EKS 기반 MLOps 플랫폼 전체는 아키텍처로 설계했으며, 실행 코드의 범위는 과제 요구사항에 따른 Dataset CRUD 4개 API와 readiness endpoint, PostgreSQL migration 및 감사 로그로 제한합니다. 전체 MLOps 플랫폼을 구현한 repository는 아닙니다.

## Architecture Documentation

- [Architecture](docs/architecture/)
- [Diagrams](docs/diagrams/)
- [Dataset API specification](docs/api-spec.md)
- [Assignment requirements](docs/requirements/argmax-mini-assignment-original.md)

설계 문서의 버전 suffix는 확정 산출물과 문서 간 참조를 보존하기 위해 유지합니다.

## Repository Structure

```text
.
├── app/                         # FastAPI application
├── alembic/versions/            # PostgreSQL migrations
├── database/                    # Reference schema
├── docs/
│   ├── architecture/            # Architecture and data-model documents
│   ├── diagrams/                # Draw.io, SVG, PNG, and Mermaid sources
│   ├── requirements/            # Original assignment requirements
│   └── verification/            # Database verification report
├── scripts/database-validation/ # Standalone schema verification bundle
├── tests/                       # PostgreSQL integration tests
├── Dockerfile
└── docker-compose.yml
```

## 실행

사전 요구사항은 Docker Engine과 `docker compose` 명령을 제공하는 Docker Compose v2입니다. 평가용 기본값이 Compose에 포함되어 있으므로 `.env` 파일이나 외부 서비스 자격증명은 필요하지 않습니다.

루트 디렉터리에서 다음 명령 하나로 DB 기동, Alembic `0001`~`0004` 자동 적용, API 기동이 진행됩니다.

```bash
docker compose up -d --build
docker compose ps
curl -i http://localhost:8000/health
```

Swagger UI는 `http://localhost:8000/docs`, OpenAPI JSON은 `http://localhost:8000/openapi.json`에서 확인합니다.

기동 로그는 `docker compose logs --no-color app db`로 확인할 수 있습니다. migration은 매 app 기동 시 `alembic upgrade head`로 먼저 적용되며, 성공한 경우에만 API 프로세스가 시작됩니다.

## API

- `POST /api/v1/datasets`
- `GET /api/v1/datasets/{dataset_id}`
- `PATCH /api/v1/datasets/{dataset_id}`
- `DELETE /api/v1/datasets/{dataset_id}`
- `GET /health` (운영 readiness endpoint)

`GET /health`는 CRUD 4개에 포함되지 않는 운영 readiness endpoint입니다.

인증·인가 시스템 전체는 과제 구현 범위에서 제외되어 있습니다. 모든 Dataset 요청은 migration이 생성하는 고정 평가 사용자 `00000000-0000-4000-8000-000000000001`의 요청으로 처리하며, 사용자 ID를 요청에서 받지 않습니다. 외부 `X-Request-ID`는 재사용하지 않고 서버가 매 요청 새 UUID를 발급합니다.

Dataset 이름은 앞뒤 공백을 제거해 저장하며, 활성 Dataset 이름은 고정 사용자 범위에서 대소문자와 앞뒤 공백을 무시하고 유일합니다. DELETE는 물리 삭제 대신 `deleted_at`을 기록하며, 삭제된 Dataset 이름은 새 Dataset에서 재사용할 수 있습니다.

## API 사용 예시

별도 인증 헤더나 `user_id`는 사용하지 않습니다. 모든 응답에는 서버가 새로 생성한 `X-Request-ID`가 포함됩니다.

생성 요청은 `201 Created`와 생성 리소스의 상대 URI를 담은 `Location` 헤더를 반환합니다.

```bash
curl -i -X POST http://localhost:8000/api/v1/datasets \
  -H 'Content-Type: application/json' \
  -d '{"name":"customer-churn","description":"Training dataset"}'
```

생성 응답의 `id`를 아래 `{dataset_id}`에 넣어 조회·부분 수정·삭제할 수 있습니다.

```bash
curl -i http://localhost:8000/api/v1/datasets/{dataset_id}

curl -i -X PATCH http://localhost:8000/api/v1/datasets/{dataset_id} \
  -H 'Content-Type: application/json' \
  -d '{"name":"customer-churn-v2","description":null}'

curl -i -X DELETE http://localhost:8000/api/v1/datasets/{dataset_id}
```

PATCH에서 생략한 필드는 기존 값을 유지하고, 명시적인 `description: null`은 설명을 제거합니다. DELETE는 `204 No Content`로 Soft Delete하며 이후 조회는 `404`입니다. 삭제된 Dataset의 정규화 이름은 새 Dataset 생성에 다시 사용할 수 있습니다.

## 평가 구현 근거

`GET /api/v1/datasets/{dataset_id}`는 `datasets`와 `dataset_versions` 두 엔티티를 단일 PostgreSQL LATERAL JOIN 문장으로 결합합니다. 상태와 관계없이 가장 큰 버전을 `latest_version`으로, READY 중 가장 큰 버전을 `latest_ready_version`으로 독립 계산하며 해당 버전이 없으면 `null`을 반환합니다. 이는 별도 버전 API를 추가하지 않고 기존 4개 API 안에서 관계 데이터를 조합하는 다중 도메인 조회입니다.

POST·PATCH·DELETE는 Dataset 변경과 SUCCESS AuditLog INSERT를 Service 계층의 동일 트랜잭션에서 flush한 뒤 한 번만 commit합니다. 감사 로그 저장을 포함한 어느 단계라도 실패하면 Dataset 변경도 rollback합니다. FAILURE AuditLog는 비즈니스 rollback 이후 별도 best-effort 트랜잭션으로 기록합니다. 실제 PostgreSQL rollback, 행 잠금, 이름 unique constraint, 단일 조회 SQL은 아래 통합 테스트로 검증합니다.

Compose에서 사용하는 주요 환경변수는 `DATABASE_URL`과 `TZ`입니다. DB 계정과 비밀번호는 제출용 로컬 Compose 전용 값이며 production credential이 아닙니다.

## Verification

통합 테스트는 Compose 내부의 실제 PostgreSQL을 사용하며 별도 `test` build target에서 실행됩니다.

```bash
docker compose run --build --rm test
docker compose run --rm test ruff check --no-cache app tests
```
