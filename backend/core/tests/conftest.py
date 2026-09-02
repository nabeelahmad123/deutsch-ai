"""A throwaway in-memory SQLite DB with a user and a few words, for the
DB-backed scheduler tests. No network, no live Postgres (DoD section 17)."""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from backend.db.models import User, Word
from backend.db.session import configure, create_all, session_scope

T0 = dt.datetime(2026, 1, 1, 9, 0, 0)


@pytest.fixture
def session() -> Iterator[Session]:
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    with session_scope() as s:
        s.add(User(id=1, target="general"))
        s.add_all(
            Word(
                id=i,
                lemma=f"wort{i}",
                translation_en=f"word {i}",
                cefr_level="A1",
                frequency_rank=i,
            )
            for i in range(1, 6)
        )
        s.flush()
        yield s
