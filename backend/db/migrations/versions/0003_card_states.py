"""materialised SM-2 state cache: card_states

Revision ID: 0003_card_states
Revises: 0002_user_login
Create Date: 2026-09-03

``review_logs`` stays the source of truth; ``card_states`` is a derived cache so
the due list / weak list / dashboard are indexed reads instead of a full replay
per request. Rows are (re)built lazily from the logs on first read after this
migration (scheduler.ensure_user_card_states), so no data step here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_card_states"
down_revision: str | None = "0002_user_login"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_states",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviews", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_reviews", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reviewed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["word_id"], ["words.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "word_id"),
    )
    op.create_index("ix_card_states_user_due", "card_states", ["user_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_card_states_user_due", table_name="card_states")
    op.drop_table("card_states")
