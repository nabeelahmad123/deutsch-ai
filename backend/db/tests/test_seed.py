"""The seeder migrates, loads vocab, and is idempotent."""

import pytest
from sqlalchemy import create_engine, func, select

from backend.db import seed as db_seed
from backend.db import session as db_session
from backend.db.models import User, Word


@pytest.fixture
def sqlite_url(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 's.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    db_session.configure(url, force=True)
    yield url
    db_session.get_engine().dispose()


def _counts(url):
    with create_engine(url).connect() as c:
        return (
            c.scalar(select(func.count()).select_from(Word)),
            c.scalar(select(func.count()).select_from(User)),
        )


def test_migrate_then_seed_then_reseed_is_idempotent(sqlite_url):
    db_seed.upgrade_to_head()

    if db_seed.WORDS_JSONL.exists():
        inserted, total = db_seed.seed_from_jsonl(db_seed.WORDS_JSONL)
        assert inserted == total > 0
        again, _ = db_seed.seed_from_jsonl(db_seed.WORDS_JSONL)
        assert again == 0
    else:  # CI without the derived corpus -> the committed seed.sql
        db_seed.seed_from_sql(db_seed.SEED_SQL)

    words, users = _counts(sqlite_url)
    assert words > 100 and users == 1


def test_sql_replay_preserves_semicolons_in_glosses(sqlite_url):
    db_seed.upgrade_to_head()
    db_seed.seed_from_sql(db_seed.SEED_SQL)
    with create_engine(sqlite_url).connect() as c:
        gloss = c.scalar(select(Word.translation_en).where(Word.lemma == "der"))
    assert gloss and ";" in gloss  # "who; that; which" survived the replay
