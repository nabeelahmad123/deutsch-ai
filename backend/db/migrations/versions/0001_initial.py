"""initial schema: words, users, review_logs, sessions

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-03

Mirrors backend/db/models.py (CLAUDE.md section 5). sa.Enum renders as a native
ENUM type on Postgres and as VARCHAR + CHECK on SQLite, so this migration runs on
both.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

cefr_level = sa.Enum("A1", "A2", "B1", "B2", name="cefr_level")
user_target = sa.Enum("work", "travel", "general", "exam", name="user_target")
review_source = sa.Enum("review", "new", name="review_source")


def upgrade() -> None:
    op.create_table(
        "words",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lemma", sa.String(length=128), nullable=False),
        sa.Column("article", sa.String(length=8), nullable=True),
        sa.Column("plural", sa.String(length=128), nullable=True),
        sa.Column("translation_en", sa.String(length=256), nullable=False),
        sa.Column("cefr_level", cefr_level, nullable=False),
        sa.Column("frequency_rank", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=True),
        sa.Column("ipa_or_audio_ref", sa.Text(), nullable=True),
    )
    # models.py: mapped_column(..., unique=True, index=True) -> one unique index
    op.create_index("ix_words_lemma", "words", ["lemma"], unique=True)
    op.create_index("ix_words_cefr_level", "words", ["cefr_level"])
    op.create_index("ix_words_frequency_rank", "words", ["frequency_rank"])
    op.create_index("ix_words_topic", "words", ["topic"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("target", user_target, nullable=False, server_default="general"),
    )

    op.create_table(
        "review_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("source", review_source, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["word_id"], ["words.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_review_logs_user_id", "review_logs", ["user_id"])
    op.create_index("ix_review_logs_word_id", "review_logs", ["word_id"])
    op.create_index("ix_review_logs_timestamp", "review_logs", ["timestamp"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("duration_minutes_requested", sa.Integer(), nullable=False),
        sa.Column("words_covered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("topic", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_index("ix_review_logs_timestamp", table_name="review_logs")
    op.drop_index("ix_review_logs_word_id", table_name="review_logs")
    op.drop_index("ix_review_logs_user_id", table_name="review_logs")
    op.drop_table("review_logs")
    op.drop_table("users")
    op.drop_index("ix_words_topic", table_name="words")
    op.drop_index("ix_words_frequency_rank", table_name="words")
    op.drop_index("ix_words_cefr_level", table_name="words")
    op.drop_index("ix_words_lemma", table_name="words")
    op.drop_table("words")
    for enum in (cefr_level, user_target, review_source):
        enum.drop(op.get_bind(), checkfirst=True)
