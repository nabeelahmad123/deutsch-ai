"""Bring a database up to head and load the vocabulary seed.

    python -m backend.db.seed                # migrate + seed from build/words.jsonl
    python -m backend.db.seed --sql-only     # migrate + replay backend/data/seed.sql

Idempotent: existing lemmas are skipped, the demo user is created only if the
users table is empty. Schema comes from Alembic (backend/db/migrations/), never
from here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from backend.data.assign_cefr import assign_cefr
from backend.data.assign_topic import assign_topic
from backend.db.models import User, Word
from backend.db.session import get_engine, resolve_url, session_scope

REPO_ROOT = Path(__file__).resolve().parents[2]
WORDS_JSONL = REPO_ROOT / "backend" / "data" / "build" / "words.jsonl"
SEED_SQL = REPO_ROOT / "backend" / "data" / "seed.sql"


def upgrade_to_head() -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", resolve_url())
    command.upgrade(cfg, "head")


def _word_rows_from_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        cefr = assign_cefr(rec["frequency_rank"])
        if cefr is None:
            continue
        rows.append(
            {
                "lemma": rec["lemma"],
                "article": rec.get("article"),
                "plural": rec.get("plural"),
                "translation_en": rec["translation_en"],
                "cefr_level": cefr,
                "frequency_rank": rec["frequency_rank"],
                "topic": rec.get("topic") or assign_topic(rec.get("translation_en"), rec["lemma"]),
                "ipa_or_audio_ref": rec.get("ipa_or_audio_ref"),
            }
        )
    return rows


def seed_from_jsonl(path: Path) -> tuple[int, int]:
    rows = _word_rows_from_jsonl(path)
    with session_scope() as session:
        existing = set(session.scalars(select(Word.lemma)))
        fresh = [r for r in rows if r["lemma"] not in existing]
        if fresh:
            session.bulk_insert_mappings(Word, fresh)
        if session.scalar(select(func.count()).select_from(User)) == 0:
            session.add(User(target="work"))
    return len(fresh), len(rows)


def seed_from_sql(path: Path) -> None:
    """Replay seed.sql as a whole script.

    Naive ``;`` splitting is wrong here -- glosses contain semicolons -- so we
    hand the entire file to the driver's multi-statement facility.
    """
    sql = path.read_text(encoding="utf-8")
    engine = get_engine()
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.connection.executescript(sql)
        else:  # psycopg3 runs multiple ;-separated statements in one call
            conn.exec_driver_sql(sql)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-only", action="store_true", help="replay seed.sql instead of jsonl")
    parser.add_argument("--skip-migrate", action="store_true", help="assume DB is already at head")
    args = parser.parse_args()

    if not args.skip_migrate:
        upgrade_to_head()

    if args.sql_only or not WORDS_JSONL.exists():
        if not SEED_SQL.exists():
            raise SystemExit(f"missing both {WORDS_JSONL} and {SEED_SQL}")
        seed_from_sql(SEED_SQL)
        print(f"replayed {SEED_SQL}")
    else:
        inserted, total = seed_from_jsonl(WORDS_JSONL)
        print(f"seeded {inserted} new / {total} words from {WORDS_JSONL.name}")


if __name__ == "__main__":
    main()
