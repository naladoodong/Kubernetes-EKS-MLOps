from app.schemas import ErrorResponse

REQUEST_ID_HEADER = {"description": "Server-generated request UUID", "schema": {"type": "string", "format": "uuid"}}

ERROR_EXAMPLES = {
    404: {
        "error": {"code": "DATASET_NOT_FOUND", "message": "Dataset was not found.", "details": []},
        "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412",
    },
    409: {
        "error": {
            "code": "DATASET_NAME_CONFLICT",
            "message": "An active Dataset with this name already exists.",
            "details": [],
        },
        "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412",
    },
    422: {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "details": [{"field": "body.name", "reason": "Field required"}],
        },
        "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412",
    },
    500: {
        "error": {"code": "INTERNAL_ERROR", "message": "An internal server error occurred.", "details": []},
        "request_id": "7eb25f9e-bf4a-44e8-a5cc-87eaa2646412",
    },
}


def error_responses(*statuses: int):
    descriptions = {
        404: "Dataset not found",
        409: "Active name conflict",
        422: "Request validation error",
        500: "Internal error",
    }
    return {
        status: {
            "model": ErrorResponse,
            "description": descriptions[status],
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {"application/json": {"example": ERROR_EXAMPLES[status]}},
        }
        for status in statuses
    }
