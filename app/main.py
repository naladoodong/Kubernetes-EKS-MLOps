import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.audit import record_failure
from app.exceptions import AppError
from app.router import router

logger = logging.getLogger(__name__)
app = FastAPI(
    title="ArgMax Mini Dataset API",
    version="1.0.0",
    description=(
        "A limited Dataset CRUD implementation from the broader ArgMax Mini MLOps design. "
        "Authentication is outside this assignment scope: every Dataset request runs as the fixed evaluator user, "
        "so clients do not provide a user ID or authentication credentials."
    ),
    openapi_tags=[
        {
            "name": "Datasets",
            "description": "Create, read, partially update, and soft-delete evaluator-owned Datasets.",
        },
        {
            "name": "Operations",
            "description": "Operational readiness endpoints; these are not part of the four Dataset CRUD APIs.",
        },
    ],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = uuid4()
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(request.state.request_id)
    return response


def error_response(request: Request, status_code: int, code: str, message: str, details: list[dict] | None = None):
    record_failure(request, status_code, code)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []},
                 "request_id": str(request.state.request_id)},
    )


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    return error_response(request, exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError):
    details = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"] if item != "__root__")
        details.append({"field": location, "reason": error["msg"]})
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed.", details)


@app.exception_handler(Exception)
def internal_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled_request_error", extra={"request_id": str(request.state.request_id)})
    return error_response(request, 500, "INTERNAL_ERROR", "An internal server error occurred.")


app.include_router(router)
