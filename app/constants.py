from uuid import UUID

EVALUATOR_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
AUDITED_ROUTES = {
    ("POST", "/api/v1/datasets"): "DATASET_CREATE",
    ("PATCH", "/api/v1/datasets/{dataset_id}"): "DATASET_UPDATE",
    ("DELETE", "/api/v1/datasets/{dataset_id}"): "DATASET_DELETE",
}
