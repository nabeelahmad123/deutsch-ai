"""Shared fixtures for API tests: a fresh in-memory SQLite DB per test."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    from backend.db import session as db_session

    db_session.configure("sqlite+pysqlite:///:memory:", force=True)
    db_session.create_all()

    from backend.api.main import app

    with TestClient(app) as c:
        yield c

    engine = db_session.get_engine()
    engine.dispose()
