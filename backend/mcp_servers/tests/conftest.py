"""In-memory SQLite seeded with a learner + words, for MCP server tests.

The server tools reach the DB via ``session_scope``, so we just point the
process engine at a fresh SQLite DB and seed it.
"""

import datetime as dt

import pytest

from backend.db.models import ReviewLog, User, Word
from backend.db.session import configure, create_all, session_scope

T0 = dt.datetime(2026, 1, 1, 9, 0, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _trace_to_tmp(tmp_path, monkeypatch):
    """Keep tool-call traces and the notes vault out of the repo during tests."""
    monkeypatch.setenv("TRACE_LOG_PATH", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("NOTES_VAULT_DIR", str(tmp_path / "vault"))


@pytest.fixture
def vault_path(tmp_path):
    return tmp_path / "vault"


@pytest.fixture
def seeded_db():
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    with session_scope() as s:
        s.add(User(id=1, target="work"))
        for i in range(1, 31):
            is_noun = i % 2 == 1  # odd ids are nouns (have an article)
            s.add(
                Word(
                    id=i,
                    lemma=f"wort{i}",
                    article="das" if is_noun else None,
                    plural=f"wort{i}e" if is_noun else None,
                    translation_en=f"word {i}",
                    cefr_level=["A1", "A2", "B1"][(i - 1) // 10],
                    frequency_rank=i,
                    topic="food" if i in (3, 7, 12) else None,
                )
            )
        # word 1 failed twice (weak + due), word 2 passed once
        s.add(
            ReviewLog(
                user_id=1,
                word_id=1,
                timestamp=T0,
                correct=False,
                response_time_ms=9000,
                source="new",
            )
        )
        s.add(
            ReviewLog(
                user_id=1,
                word_id=1,
                timestamp=T0 + dt.timedelta(days=1),
                correct=False,
                response_time_ms=9000,
                source="review",
            )
        )
        s.add(
            ReviewLog(
                user_id=1, word_id=2, timestamp=T0, correct=True, response_time_ms=700, source="new"
            )
        )
    yield
