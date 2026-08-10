from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_session
from app.openapi import REQUEST_ID_HEADER, error_responses
from app.schemas import (
    DatasetCreateRequest,
    DatasetDetailResponse,
    DatasetResponse,
    DatasetUpdateRequest,
    HealthResponse,
)
from app.services import service

router = APIRouter()
DbSession = Annotated[Session, Depends(get_session)]
DatasetId = Annotated[
    UUID,
    Path(
        description="Dataset UUID. Only active resources owned by the fixed evaluator user are visible.",
        examples=["0a89cb0c-c78b-4c68-9f41-3f3fa7238131"],
    ),
]


@router.post(
    "/api/v1/datasets", response_model=DatasetResponse, status_code=201, operation_id="createDataset",
    tags=["Datasets"],
    summary="Create a Dataset",
    description=(
        "Creates a Dataset owned by the fixed evaluator user; no user ID or authentication input is required. "
        "The name is trimmed before validation and storage. Active names are unique for that user after "
        "case-insensitive, surrounding-whitespace normalization; conflicts return 409. Names of soft-deleted "
        "Datasets may be reused. A successful response is 201, with Location identifying the new resource and "
        "X-Request-ID containing the server-generated request UUID."
    ),
    responses={201: {"headers": {"Location": {"description": "Relative resource URI", "schema": {"type": "string"}},
                                      "X-Request-ID": REQUEST_ID_HEADER}}, **error_responses(409, 422, 500)},
)
def create_dataset(body: DatasetCreateRequest, request: Request, response: Response, session: DbSession):
    dataset = service.create(session, body, str(request.state.request_id))
    response.headers["Location"] = f"/api/v1/datasets/{dataset.id}"
    return dataset


@router.get(
    "/api/v1/datasets/{dataset_id}", response_model=DatasetDetailResponse, operation_id="getDataset",
    tags=["Datasets"],
    summary="Get Dataset details",
    description=(
        "Returns one active Dataset owned by the fixed evaluator user. Missing, soft-deleted, and differently "
        "owned resources all return 404. latest_version is the greatest version number regardless of status; "
        "latest_ready_version is the greatest version number whose status is READY. Either is null when no "
        "matching version exists. X-Request-ID contains the server-generated request UUID."
    ),
    responses={200: {"headers": {"X-Request-ID": REQUEST_ID_HEADER}}, **error_responses(404, 422, 500)},
)
def get_dataset(dataset_id: DatasetId, request: Request, session: DbSession):
    return service.get(session, dataset_id)


@router.patch(
    "/api/v1/datasets/{dataset_id}", response_model=DatasetResponse, operation_id="updateDataset",
    tags=["Datasets"],
    summary="Partially update a Dataset",
    description=(
        "Partially updates an active Dataset owned by the fixed evaluator user. Omitted fields remain unchanged; "
        "description: null removes the description, while name cannot be null. An empty object is rejected with "
        "422. Supplied names are trimmed and normalized-name conflicts return 409. Missing or soft-deleted "
        "resources return 404. X-Request-ID contains the server-generated request UUID."
    ),
    responses={200: {"headers": {"X-Request-ID": REQUEST_ID_HEADER}}, **error_responses(404, 409, 422, 500)},
)
def update_dataset(dataset_id: DatasetId, body: DatasetUpdateRequest, request: Request, session: DbSession):
    return service.update(session, dataset_id, body, str(request.state.request_id))


@router.delete(
    "/api/v1/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteDataset",
    tags=["Datasets"],
    summary="Soft-delete a Dataset",
    description=(
        "Soft-deletes an active Dataset owned by the fixed evaluator user; no row is physically deleted. "
        "The resource returns 404 to later reads, updates, and deletes, while its normalized name may be reused "
        "for a new Dataset. Missing or already deleted resources return 404. Success is 204 with no response body "
        "or Content-Type; X-Request-ID still contains the server-generated request UUID."
    ),
    response_class=Response,
    responses={204: {"description": "Dataset soft-deleted", "headers": {"X-Request-ID": REQUEST_ID_HEADER}},
               **error_responses(404, 422, 500)},
)
def delete_dataset(dataset_id: DatasetId, request: Request, session: DbSession):
    service.delete(session, dataset_id, str(request.state.request_id))
    return Response(status_code=204)


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="healthCheck",
    tags=["Operations"],
    summary="Check application readiness",
    description=(
        "Returns 200 only when the API process can reach PostgreSQL. This operational endpoint is not one of the "
        "four Dataset CRUD APIs and exposes no database connection details."
    ),
    responses={200: {"headers": {"X-Request-ID": REQUEST_ID_HEADER}}, **error_responses(500)},
)
def health(session: DbSession):
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
