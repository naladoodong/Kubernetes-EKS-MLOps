from uuid import UUID

from sqlalchemy import Select, exists, func, select, text
from sqlalchemy.orm import Session

from app.models import AuditLog, Dataset


class DatasetRepository:
    def active_name_exists(self, session: Session, user_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        query: Select = select(
            exists().where(
                Dataset.user_id == user_id,
                Dataset.deleted_at.is_(None),
                func.lower(func.btrim(Dataset.name)) == name.strip().lower(),
                *([Dataset.id != exclude_id] if exclude_id else []),
            )
        )
        return bool(session.scalar(query))

    def get_active(self, session: Session, user_id: UUID, dataset_id: UUID, *, lock: bool = False) -> Dataset | None:
        query = select(Dataset).where(
            Dataset.id == dataset_id, Dataset.user_id == user_id, Dataset.deleted_at.is_(None)
        )
        if lock:
            query = query.with_for_update()
        return session.scalar(query)

    def get_detail(self, session: Session, user_id: UUID, dataset_id: UUID):
        # One PostgreSQL statement; both LATERAL subqueries can use the documented indexes.
        return session.execute(
            text(
                """
                SELECT d.id, d.name, d.description, d.created_at, d.updated_at,
                       lv.version_number AS latest_version_number, lv.status AS latest_version_status,
                       lrv.version_number AS ready_version_number, lrv.status AS ready_version_status
                FROM datasets AS d
                LEFT JOIN LATERAL (
                    SELECT version_number, status FROM dataset_versions
                    WHERE dataset_id = d.id ORDER BY version_number DESC LIMIT 1
                ) AS lv ON true
                LEFT JOIN LATERAL (
                    SELECT version_number, status FROM dataset_versions
                    WHERE dataset_id = d.id AND status = 'READY'
                    ORDER BY version_number DESC LIMIT 1
                ) AS lrv ON true
                WHERE d.id = :dataset_id AND d.user_id = :user_id AND d.deleted_at IS NULL
                """
            ),
            {"dataset_id": dataset_id, "user_id": user_id},
        ).mappings().one_or_none()


class AuditRepository:
    def add(
        self,
        session: Session,
        *,
        action: str,
        request_id: str,
        result: str,
        http_status: int,
        resource_id: UUID | None,
        actor_user_id: UUID,
        error_code: str | None = None,
    ) -> None:
        session.add(
            AuditLog(
                actor_type="USER",
                actor_user_id=actor_user_id,
                action=action,
                resource_type="DATASET",
                resource_id=resource_id,
                request_id=request_id,
                result=result,
                error_code=error_code,
                metadata_json={"http_status": http_status},
            )
        )
