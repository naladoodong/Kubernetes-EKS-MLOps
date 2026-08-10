from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text

from app.database import SessionLocal, engine
from app.repositories import AuditRepository, DatasetRepository
from app.schemas import DatasetCreateRequest, DatasetUpdateRequest


def assert_request_id(response):
    value = response.headers["X-Request-ID"]
    UUID(value)
    if response.status_code >= 400:
        assert response.json()["request_id"] == value
    return value


def audit_rows():
    with SessionLocal() as session:
        return session.execute(text("SELECT * FROM audit_logs ORDER BY occurred_at")).mappings().all()


def test_create_contract_trim_location_and_success_audit(client):
    response = client.post("/api/v1/datasets", headers={"X-Request-ID": "external"},
                           json={"name": "  Customer-Churn  ", "description": " x "})
    assert response.status_code == 201
    request_id = assert_request_id(response)
    assert request_id != "external"
    assert response.json()["name"] == "Customer-Churn"
    assert response.json()["description"] == " x "
    assert response.headers["Location"].endswith(response.json()["id"])
    row = audit_rows()[0]
    assert (row.result, row.action, row.error_code, row.metadata_json) == (
        "SUCCESS", "DATASET_CREATE", None, {"http_status": 201}
    )


def test_create_conflict_case_space_and_failure_audit(client, create_dataset):
    create_dataset("Customer-Churn")
    response = client.post("/api/v1/datasets", json={"name": " customer-churn "})
    assert response.status_code == 409
    assert_request_id(response)
    assert response.json()["error"]["code"] == "DATASET_NAME_CONFLICT"
    failure = audit_rows()[-1]
    assert failure.result == "FAILURE"
    assert failure.resource_id is None
    assert failure.error_code == "DATASET_NAME_CONFLICT"
    assert failure.metadata_json == {"http_status": 409}


def test_create_database_unique_conflict_rolls_back_and_returns_409(client, create_dataset, monkeypatch):
    create_dataset("database-guard")
    monkeypatch.setattr(DatasetRepository, "active_name_exists", lambda *args, **kwargs: False)

    response = client.post("/api/v1/datasets", json={"name": " DATABASE-GUARD "})

    assert response.status_code == 409
    assert_request_id(response)
    assert response.json()["error"]["code"] == "DATASET_NAME_CONFLICT"
    with SessionLocal() as session:
        assert session.scalar(text("SELECT count(*) FROM datasets WHERE lower(btrim(name))='database-guard'")) == 1
    failure = audit_rows()[-1]
    assert failure.result == "FAILURE"
    assert failure.error_code == "DATASET_NAME_CONFLICT"
    assert failure.metadata_json == {"http_status": 409}


@pytest.mark.parametrize("payload", [{"name": "   "}, {"name": "x", "unknown": 1}, {}])
def test_create_validation_common_error_and_failure_audit(client, payload):
    response = client.post("/api/v1/datasets", json=payload)
    assert response.status_code == 422
    assert_request_id(response)
    assert set(response.json()) == {"error", "request_id"}
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert audit_rows()[0].metadata_json == {"http_status": 422}


def test_get_version_summaries_in_one_statement(client, create_dataset):
    dataset_id = create_dataset().json()["id"]
    other_id = create_dataset("other").json()["id"]
    with SessionLocal() as session:
        for number, status in [(1, "FAILED"), (2, "READY"), (3, "PROCESSING")]:
            session.execute(text("""INSERT INTO dataset_versions
                (dataset_id, version_number, original_filename, file_format, status)
                VALUES (:id, :number, :filename, 'CSV', :status)"""),
                {"id": dataset_id, "number": number, "filename": f"{number}.csv", "status": status})
        session.execute(text("""INSERT INTO dataset_versions
            (dataset_id, version_number, original_filename, file_format, status)
            VALUES (:id, 99, 'other.csv', 'CSV', 'READY')"""), {"id": other_id})
        session.commit()
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/v1/datasets/{dataset_id}")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["latest_version"] == {"version_number": 3, "status": "PROCESSING"}
    assert response.json()["latest_ready_version"] == {"version_number": 2, "status": "READY"}
    assert sum("FROM datasets AS d" in statement for statement in statements) == 1


def test_get_without_versions_and_get_failure_not_audited(client, create_dataset):
    dataset_id = create_dataset().json()["id"]
    assert client.get(f"/api/v1/datasets/{dataset_id}").json()["latest_version"] is None
    before = len(audit_rows())
    response = client.get(f"/api/v1/datasets/{uuid4()}")
    assert response.status_code == 404
    assert len(audit_rows()) == before


def test_get_with_versions_but_without_ready_version(client, create_dataset):
    dataset_id = create_dataset().json()["id"]
    with SessionLocal() as session:
        session.execute(text("""INSERT INTO dataset_versions
            (dataset_id, version_number, original_filename, file_format, status)
            VALUES (:id, 1, 'processing.csv', 'CSV', 'PROCESSING')"""), {"id": dataset_id})
        session.commit()
    response = client.get(f"/api/v1/datasets/{dataset_id}")
    assert response.status_code == 200
    assert response.json()["latest_version"] == {"version_number": 1, "status": "PROCESSING"}
    assert response.json()["latest_ready_version"] is None


def test_get_rejects_deleted_and_other_owner(client, create_dataset):
    dataset_id = create_dataset().json()["id"]
    assert client.delete(f"/api/v1/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    other_user, other_dataset = uuid4(), uuid4()
    with SessionLocal() as session:
        session.execute(text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                        {"id": other_user, "email": f"{other_user}@example.test"})
        session.execute(text("INSERT INTO datasets (id, user_id, name) VALUES (:id, :user, 'private')"),
                        {"id": other_dataset, "user": other_user})
        session.commit()
    assert client.get(f"/api/v1/datasets/{other_dataset}").status_code == 404


def test_patch_partial_null_same_value_timestamp_and_lock(client, create_dataset):
    created = create_dataset(description="present").json()
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.patch(f"/api/v1/datasets/{created['id']}", json={"description": None})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["name"] == created["name"]
    assert response.json()["description"] is None
    assert response.json()["updated_at"] > created["updated_at"]
    assert any("FOR UPDATE" in statement for statement in statements)


def test_patch_name_conflict(client, create_dataset):
    first_id = create_dataset("first").json()["id"]
    create_dataset("second")
    response = client.patch(f"/api/v1/datasets/{first_id}", json={"name": " SECOND "})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_NAME_CONFLICT"


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"unknown": 1}])
def test_patch_validation(client, create_dataset, payload):
    dataset_id = create_dataset().json()["id"]
    response = client.patch(f"/api/v1/datasets/{dataset_id}", json=payload)
    assert response.status_code == 422
    assert_request_id(response)


def test_delete_empty_soft_delete_repeated_and_name_reuse(client, create_dataset):
    dataset_id = create_dataset("reusable").json()["id"]
    response = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert_request_id(response)
    assert client.delete(f"/api/v1/datasets/{dataset_id}").status_code == 404
    assert client.post("/api/v1/datasets", json={"name": " REUSABLE "}).status_code == 201


def test_delete_uses_row_lock(client, create_dataset):
    dataset_id = create_dataset().json()["id"]
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.delete(f"/api/v1/datasets/{dataset_id}")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 204
    assert any("FOR UPDATE" in statement for statement in statements)


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_success_audit_failure_rolls_back(client, create_dataset, monkeypatch, method):
    dataset_id = create_dataset("original", "before").json()["id"]
    original = AuditRepository.add
    def fail_success(self, session, **kwargs):
        if kwargs["result"] == "SUCCESS":
            raise RuntimeError("forced audit failure")
        return original(self, session, **kwargs)
    monkeypatch.setattr(AuditRepository, "add", fail_success)
    if method == "patch":
        response = client.patch(f"/api/v1/datasets/{dataset_id}", json={"name": "changed"})
    else:
        response = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert response.status_code == 500
    assert "forced" not in response.text
    with SessionLocal() as session:
        row = session.execute(text("SELECT name, deleted_at FROM datasets WHERE id=:id"), {"id": dataset_id}).one()
        assert row.name == "original"
        assert row.deleted_at is None


def test_create_success_audit_failure_rolls_back(client, monkeypatch):
    original = AuditRepository.add
    def fail_success(self, session, **kwargs):
        if kwargs["result"] == "SUCCESS":
            raise RuntimeError("forced audit failure")
        return original(self, session, **kwargs)
    monkeypatch.setattr(AuditRepository, "add", fail_success)
    response = client.post("/api/v1/datasets", json={"name": "must-roll-back"})
    assert response.status_code == 500
    with SessionLocal() as session:
        assert session.scalar(text("SELECT count(*) FROM datasets WHERE name='must-roll-back'")) == 0


def test_failure_audit_is_best_effort(client, create_dataset, monkeypatch):
    create_dataset("conflicting")
    original = AuditRepository.add
    def fail_failure(self, session, **kwargs):
        if kwargs["result"] == "FAILURE":
            raise RuntimeError("forced failure audit error")
        return original(self, session, **kwargs)
    monkeypatch.setattr(AuditRepository, "add", fail_failure)
    response = client.post("/api/v1/datasets", json={"name": "CONFLICTING"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_NAME_CONFLICT"


def test_invalid_uuid_failure_audit_has_null_resource(client):
    response = client.delete("/api/v1/datasets/not-a-uuid")
    assert response.status_code == 422
    assert_request_id(response)
    assert audit_rows()[0].resource_id is None


def test_health_has_request_id_and_no_audit(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert_request_id(response)
    assert audit_rows() == []


def test_openapi_contract(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    create = paths["/api/v1/datasets"]["post"]
    detail = paths["/api/v1/datasets/{dataset_id}"]
    operations = {
        "post": create,
        "get": detail["get"],
        "patch": detail["patch"],
        "delete": detail["delete"],
    }

    assert document["info"]["title"] == "ArgMax Mini Dataset API"
    assert document["info"]["version"] == "1.0.0"
    assert all(term in document["info"]["description"] for term in ("limited", "fixed evaluator user"))
    assert {tag["name"] for tag in document["tags"]} == {"Datasets", "Operations"}
    assert "servers" not in document
    assert "security" not in document

    assert set(paths) == {"/api/v1/datasets", "/api/v1/datasets/{dataset_id}", "/health"}
    assert set(paths["/api/v1/datasets"]) == {"post"}
    assert {method for method in detail if method in {"get", "patch", "delete"}} == {"get", "patch", "delete"}
    assert [operations[method]["operationId"] for method in operations] == [
        "createDataset", "getDataset", "updateDataset", "deleteDataset"
    ]
    assert len({operation["operationId"] for operation in operations.values()}) == 4
    assert all(operation["summary"] and operation["description"] for operation in operations.values())
    assert all(operation["tags"] == ["Datasets"] for operation in operations.values())

    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DatasetCreateRequest"
    )
    assert detail["patch"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DatasetUpdateRequest"
    )
    assert create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DatasetResponse"
    )
    assert detail["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DatasetDetailResponse"
    )
    assert detail["patch"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DatasetResponse"
    )

    assert set(create["responses"]) == {"201", "409", "422", "500"}
    assert set(detail["get"]["responses"]) == {"200", "404", "422", "500"}
    assert set(detail["patch"]["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(detail["delete"]["responses"]) == {"204", "404", "422", "500"}
    for operation in operations.values():
        for response_document in operation["responses"].values():
            assert "X-Request-ID" in response_document["headers"]
    assert "Location" in create["responses"]["201"]["headers"]
    assert "content" not in detail["delete"]["responses"]["204"]

    schemas = document["components"]["schemas"]
    assert "user_id" not in schemas["DatasetCreateRequest"]["properties"]
    assert "user_id" not in schemas["DatasetUpdateRequest"]["properties"]
    assert schemas["DatasetCreateRequest"]["properties"]["name"]["minLength"] == 1
    assert schemas["DatasetCreateRequest"]["properties"]["name"]["maxLength"] == 255
    assert "anyOf" not in schemas["DatasetUpdateRequest"]["properties"]["name"]
    assert "anyOf" in schemas["DatasetUpdateRequest"]["properties"]["description"]
    assert "null" in str(schemas["DatasetDetailResponse"]["properties"]["latest_version"])

    create_example = schemas["DatasetCreateRequest"]["examples"][0]
    update_example = schemas["DatasetUpdateRequest"]["examples"][0]
    assert DatasetCreateRequest.model_validate(create_example)
    assert DatasetUpdateRequest.model_validate(update_example)

    assert paths["/health"]["get"]["tags"] == ["Operations"]
    assert paths["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/HealthResponse")
    assert "HTTPValidationError" not in str(document)
