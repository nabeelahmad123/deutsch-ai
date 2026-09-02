"""A throwaway in-memory SQLite DB with a user and a spread of words, for the
DB-backed scheduler tests. No network, no live Postgres (DoD section 17)."""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from backend.db.models import User, Word
from backend.db.session import configure, create_all, session_scope

T0 = dt.datetime(2026, 1, 1, 9, 0, 0)

# 40 words, ranks 1..40, ten per CEFR band, a couple carrying a topic.
_CEFR_BANDS = ["A1", "A2", "B1", "B2"]


def _seed_words(s: Session) -> None:
    for i in range(1, 41):
        band = _CEFR_BANDS[(i - 1) // 10]
        topic = "food" if i in (3, 7, 15) else ("travel" if i in (12, 22) else None)
        s.add(
            Word(
                id=i,
                lemma=f"wort{i}",
                translation_en=f"word {i}",
                cefr_level=band,
                frequency_rank=i,
                topic=topic,
            )
        )


@pytest.fixture
def session() -> Iterator[Session]:
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    with session_scope() as s:
        s.add(User(id=1, target="general"))
        _seed_words(s)
        s.flush()
        yield s
