"""diagnostic error label on review_logs

Revision ID: 0004_review_error_type
Revises: 0003_card_states
Create Date: 2026-09-05

Free-text grading (backend/study/grading.diagnose) classifies *why* an answer
was wrong -- wrong_gender / wrong_plural / spelling / false_friend /
wrong_meaning / blank / other. Nullable: correct answers and self-graded swipes
leave it NULL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_review_error_type"
down_revision: str | None = "0003_card_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_logs", sa.Column("error_type", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("review_logs", "error_type")
