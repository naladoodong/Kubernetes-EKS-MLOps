import logging
from uuid import UUID

from app.constants import AUDITED_ROUTES, EVALUATOR_USER_ID
from app.database import SessionLocal
from app.repositories import AuditRepository

logger = logging.getLogger(__name__)


def audited_action(request) -> str | None:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return AUDITED_ROUTES.get((request.method, template))


def resource_id_for_failure(request) -> UUID | None:
    if request.method == "POST":
        return None
    raw = request.path_params.get("dataset_id")
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def record_failure(request, status_code: int, error_code: str) -> None:
    action = audited_action(request)
    if action is None:
        return
    try:
        with SessionLocal() as session:
            AuditRepository().add(
                session, action=action, request_id=str(request.state.request_id), result="FAILURE",
                http_status=status_code, resource_id=resource_id_for_failure(request),
                actor_user_id=EVALUATOR_USER_ID, error_code=error_code,
            )
            session.commit()
    except Exception:
        logger.warning("failure_audit_write_failed", extra={"request_id": str(request.state.request_id)}, exc_info=True)
