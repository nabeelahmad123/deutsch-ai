"""In-memory DB (user 1 + a spread of words) for study-layer DB tests."""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from backend.db.models import User, Word
from backend.db.session import configure, create_all, session_scope

T0 = dt.datetime(2026, 1, 1, 9, 0, 0, tzinfo=dt.UTC)
_BANDS = ["A1", "A2", "B1", "B2"]


@pytest.fixture
def session() -> Iterator[Session]:
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    with session_scope() as s:
        s.add(User(id=1, target="general"))
        for i in range(1, 41):
            s.add(
                Word(
                    id=i,
                    lemma=f"wort{i}",
                    article="die" if i % 2 else None,
                    plural=f"woerter{i}" if i % 2 else None,
                    translation_en=f"word {i}",
                    cefr_level=_BANDS[(i - 1) // 10],
                    frequency_rank=i,
                    topic="cafe" if i in (2, 4) else None,
                )
            )
        s.flush()
        yield s
