"""add optional username / password_hash to users (lightweight login)

Revision ID: 0002_user_login
Revises: 0001_initial
Create Date: 2026-09-03

Both columns are nullable: anonymous users (the agent, the learner simulator,
test fixtures) keep NULL, and only ``POST /auth/register`` populates them. A
unique index on ``username`` still permits many NULLs on both SQLite and
Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_user_login"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=256), nullable=True))
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "username")
