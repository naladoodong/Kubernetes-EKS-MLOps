from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

DatasetName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetCreateRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "customer-churn", "description": "Training dataset"}]},
    )
    name: DatasetName = Field(
        description="Dataset name. Trimmed before validation and storage; active normalized names must be unique.",
        examples=["customer-churn"],
    )
    description: str | None = Field(
        default=None,
        description="Optional free-text description. Empty strings are allowed and the value is not trimmed.",
        examples=["Customer churn training dataset"],
    )


class DatasetUpdateRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "customer-churn-v2", "description": None}]},
    )
    name: DatasetName | SkipJsonSchema[None] = Field(
        default=None,
        description="New name. Omit to preserve the current name; when supplied it cannot be null.",
        examples=["customer-churn-v2"],
    )
    description: str | None = Field(
        default=None,
        description="New description. Omit to preserve it; explicit null removes it.",
        examples=["Updated training dataset"],
    )

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null.")
        return self


class DatasetResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [{
                "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
                "name": "customer-churn",
                "description": "Training dataset",
                "created_at": "2026-08-07T08:30:15.123456Z",
                "updated_at": "2026-08-07T08:30:15.123456Z",
            }]
        },
    )
    id: UUID = Field(description="Dataset UUID", examples=["0a89cb0c-c78b-4c68-9f41-3f3fa7238131"])
    name: str = Field(description="Trimmed stored Dataset name", examples=["customer-churn"])
    description: str | None = Field(description="Stored description, or null when absent")
    created_at: datetime = Field(description="Creation time in UTC")
    updated_at: datetime = Field(description="Last update time in UTC")


class DatasetVersionStatus(StrEnum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class DatasetVersionSummary(BaseModel):
    version_number: int = Field(gt=0, description="Positive version number within the Dataset", examples=[3])
    status: DatasetVersionStatus = Field(description="Processing status of this DatasetVersion")


class DatasetDetailResponse(DatasetResponse):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "id": "0a89cb0c-c78b-4c68-9f41-3f3fa7238131",
                "name": "customer-churn",
                "description": None,
                "created_at": "2026-08-07T08:30:15.123456Z",
                "updated_at": "2026-08-07T08:30:15.123456Z",
                "latest_version": {"version_number": 3, "status": "PROCESSING"},
                "latest_ready_version": {"version_number": 2, "status": "READY"},
            }]
        }
    )
    latest_version: DatasetVersionSummary | None = Field(
        description="Highest version_number regardless of status; null when the Dataset has no versions."
    )
    latest_ready_version: DatasetVersionSummary | None = Field(
        description="Highest READY version_number; null when the Dataset has no READY version."
    )


class ErrorDetail(BaseModel):
    field: str = Field(description="Request location that failed validation", examples=["body.name"])
    reason: str = Field(description="Safe validation failure reason", examples=["Field required"])


class ErrorBody(BaseModel):
    code: str = Field(description="Stable application error code", examples=["DATASET_NOT_FOUND"])
    message: str = Field(description="Client-safe error summary", examples=["Dataset was not found."])
    details: list[ErrorDetail] = Field(description="Validation details, or an empty list")


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "error": {"code": "DATASET_NOT_FOUND", "message": "Dataset was not found.", "details": []},
                "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412",
            }]
        }
    )
    error: ErrorBody = Field(description="Structured error information")
    request_id: UUID = Field(description="Same server-generated UUID returned in X-Request-ID")


class HealthResponse(BaseModel):
    status: str = Field(description="Readiness status", examples=["ok"])
