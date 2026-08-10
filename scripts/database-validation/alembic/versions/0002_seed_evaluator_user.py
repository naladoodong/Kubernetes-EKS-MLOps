"""Seed the fixed evaluator user used by local assessment.

Revision ID: 0002_seed_evaluator_user
Revises: 0001_initial_schema
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seed_evaluator_user"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVALUATOR_USER_ID = "00000000-0000-4000-8000-000000000001"
EVALUATOR_EMAIL = "evaluator@argmax-mini.local"


def upgrade() -> None:
    """Insert the deterministic evaluator ownership record."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, email)
            VALUES (CAST(:user_id AS uuid), :email)
            """
        ),
        {"user_id": EVALUATOR_USER_ID, "email": EVALUATOR_EMAIL},
    )


def downgrade() -> None:
    """Remove only the unchanged evaluator seed record.

    This intentionally fails through FK RESTRICT if dependent evaluator-owned
    resources still exist. Migration downgrade must not erase those resources.
    """
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM users
            WHERE id = CAST(:user_id AS uuid)
              AND lower(btrim(email)) = lower(btrim(:email))
            """
        ),
        {"user_id": EVALUATOR_USER_ID, "email": EVALUATOR_EMAIL},
    )
