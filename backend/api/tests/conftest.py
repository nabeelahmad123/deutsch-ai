"""Shared fixtures for API tests: a fresh migrated SQLite DB per test.

Uses a temp-file SQLite DB (not ``:memory:``) so the Alembic upgrade and the
app's engine see the same database -- this exercises the real migration path
(backend/db/migrations/) rather than ``Base.metadata.create_all``.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    from backend.db import seed as db_seed
    from backend.db import session as db_session

    db_seed.upgrade_to_head()
    db_session.configure(url, force=True)

    from backend.api.main import app

    with TestClient(app) as c:
        yield c

    db_session.get_engine().dispose()
