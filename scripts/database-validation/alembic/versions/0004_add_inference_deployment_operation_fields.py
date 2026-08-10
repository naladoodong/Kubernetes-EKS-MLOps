"""Add desired-versus-applied deployment operation fields.

Revision ID: 0004_deployment_operations
Revises: 0003_training_target_column
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0004_deployment_operations"
down_revision: str | None = "0003_training_target_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("inference_deployments", sa.Column("operation_started_at", sa.DateTime(timezone=True)))
    op.add_column("inference_deployments", sa.Column("applied_min_replicas", sa.Integer()))
    op.add_column("inference_deployments", sa.Column("applied_max_replicas", sa.Integer()))
    op.create_check_constraint("ck_inference_deployments_operation_started_after_creation", "inference_deployments", "operation_started_at IS NULL OR operation_started_at >= created_at")
    op.create_check_constraint("ck_inference_deployments_applied_replica_range", "inference_deployments", "(applied_min_replicas IS NULL AND applied_max_replicas IS NULL) OR (applied_min_replicas >= 1 AND applied_max_replicas >= applied_min_replicas)")

def downgrade() -> None:
    op.drop_constraint("ck_inference_deployments_applied_replica_range", "inference_deployments", type_="check")
    op.drop_constraint("ck_inference_deployments_operation_started_after_creation", "inference_deployments", type_="check")
    op.drop_column("inference_deployments", "applied_max_replicas")
    op.drop_column("inference_deployments", "applied_min_replicas")
    op.drop_column("inference_deployments", "operation_started_at")
