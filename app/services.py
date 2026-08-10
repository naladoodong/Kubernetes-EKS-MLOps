from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import EVALUATOR_USER_ID
from app.exceptions import DatasetNameConflict, DatasetNotFound
from app.models import Dataset
from app.repositories import AuditRepository, DatasetRepository
from app.schemas import DatasetCreateRequest, DatasetUpdateRequest

datasets = DatasetRepository()
audits = AuditRepository()


def _is_name_conflict(exc: IntegrityError) -> bool:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_datasets_active_user_name"


class DatasetService:
    def create(self, session: Session, body: DatasetCreateRequest, request_id: str) -> Dataset:
        try:
            if datasets.active_name_exists(session, EVALUATOR_USER_ID, body.name):
                raise DatasetNameConflict()
            dataset = Dataset(user_id=EVALUATOR_USER_ID, name=body.name, description=body.description)
            session.add(dataset)
            session.flush()
            audits.add(session, action="DATASET_CREATE", request_id=request_id, result="SUCCESS", http_status=201,
                       resource_id=dataset.id, actor_user_id=EVALUATOR_USER_ID)
            session.flush()
            session.commit()
            return dataset
        except IntegrityError as exc:
            session.rollback()
            if _is_name_conflict(exc):
                raise DatasetNameConflict() from exc
            raise
        except Exception:
            session.rollback()
            raise

    def get(self, session: Session, dataset_id: UUID):
        row = datasets.get_detail(session, EVALUATOR_USER_ID, dataset_id)
        if row is None:
            raise DatasetNotFound()
        return {
            "id": row.id, "name": row.name, "description": row.description,
            "created_at": row.created_at, "updated_at": row.updated_at,
            "latest_version": None if row.latest_version_number is None else {
                "version_number": row.latest_version_number, "status": row.latest_version_status
            },
            "latest_ready_version": None if row.ready_version_number is None else {
                "version_number": row.ready_version_number, "status": row.ready_version_status
            },
        }

    def update(self, session: Session, dataset_id: UUID, body: DatasetUpdateRequest, request_id: str) -> Dataset:
        try:
            dataset = datasets.get_active(session, EVALUATOR_USER_ID, dataset_id, lock=True)
            if dataset is None:
                raise DatasetNotFound()
            if "name" in body.model_fields_set:
                assert body.name is not None
                if datasets.active_name_exists(session, EVALUATOR_USER_ID, body.name, dataset.id):
                    raise DatasetNameConflict()
                dataset.name = body.name
            if "description" in body.model_fields_set:
                dataset.description = body.description
            dataset.updated_at = datetime.now(UTC)
            audits.add(session, action="DATASET_UPDATE", request_id=request_id, result="SUCCESS", http_status=200,
                       resource_id=dataset.id, actor_user_id=EVALUATOR_USER_ID)
            session.flush()
            session.commit()
            return dataset
        except IntegrityError as exc:
            session.rollback()
            if _is_name_conflict(exc):
                raise DatasetNameConflict() from exc
            raise
        except Exception:
            session.rollback()
            raise

    def delete(self, session: Session, dataset_id: UUID, request_id: str) -> None:
        try:
            dataset = datasets.get_active(session, EVALUATOR_USER_ID, dataset_id, lock=True)
            if dataset is None:
                raise DatasetNotFound()
            dataset.deleted_at = datetime.now(UTC)
            audits.add(session, action="DATASET_DELETE", request_id=request_id, result="SUCCESS", http_status=204,
                       resource_id=dataset.id, actor_user_id=EVALUATOR_USER_ID)
            session.flush()
            session.commit()
        except Exception:
            session.rollback()
            raise


service = DatasetService()
