"""Add immutable TrainingJob target-column provenance.

Revision ID: 0003_training_target_column
Revises: 0002_seed_evaluator_user
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0003_training_target_column"
down_revision: str | None = "0002_seed_evaluator_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM training_jobs)")).scalar():
        raise RuntimeError("training_jobs rows require explicit target_column_id backfill")
    op.add_column("training_jobs", sa.Column("target_column_id", sa.Uuid(), nullable=False))
    op.create_foreign_key("fk_training_jobs_target_column", "training_jobs", "dataset_columns", ["target_column_id"], ["id"], ondelete="RESTRICT")
    op.create_index("idx_training_jobs_target_column", "training_jobs", ["target_column_id"])

def downgrade() -> None:
    op.drop_index("idx_training_jobs_target_column", table_name="training_jobs")
    op.drop_constraint("fk_training_jobs_target_column", "training_jobs", type_="foreignkey")
    op.drop_column("training_jobs", "target_column_id")
