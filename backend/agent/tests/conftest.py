"""Seeded in-memory DB + tmp trace path for agent tests."""

import datetime as dt

import pytest

from backend.db.models import ReviewLog, User, Word
from backend.db.session import configure, create_all, session_scope

T0 = dt.datetime(2026, 1, 1, 9, 0, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _trace_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_LOG_PATH", str(tmp_path / "trace.jsonl"))


@pytest.fixture
def seeded_db():
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    with session_scope() as s:
        s.add(User(id=1, target="work"))
        for i in range(1, 41):
            s.add(
                Word(
                    id=i,
                    lemma=f"wort{i}",
                    article="das" if i % 2 else None,
                    translation_en=f"word {i}",
                    cefr_level=["A1", "A2", "B1", "B2"][(i - 1) // 10],
                    frequency_rank=i,
                    topic="work" if i in (2, 4, 6) else None,
                )
            )
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
    yield
