"""Drive the REAL scheduler + DB, then validate one eval metric against it.

The offline evaluation (evaluate.py) runs SM-2 in memory. Here we run the actual
``backend.core.scheduler`` against a real (in-memory SQLite) ``review_logs``
table over a multi-day timeline, with a ``Simulator`` deciding each outcome. The
recall accuracy of those real ``review_logs`` rows should match the offline
eval's SM-2 number -- that is the section-17 "validated against your own logged
real sessions" check.
"""

from __future__ import annotations

import datetime as dt
import random

from backend.core import scheduler
from backend.db.models import ReviewLog, User, Word
from backend.db.session import configure, create_all, session_scope
from backend.learner_model.metrics import recall_accuracy
from backend.learner_model.simulator import PRESETS, MemoryState, Simulator

_EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def collect_real_review_logs(
    *, n_users: int = 6, n_words: int = 30, days: int = 90, seed: int = 0
) -> dict:
    """Run the real scheduler for ``days`` and return metrics over the persisted
    ``review_logs`` (source='review')."""
    configure("sqlite+pysqlite:///:memory:", force=True)
    create_all()
    rng = random.Random(seed)

    with session_scope() as session:
        for uid in range(1, n_users + 1):
            session.add(User(id=uid, target="general"))
        for wid in range(1, n_words + 1):
            session.add(
                Word(
                    id=wid,
                    lemma=f"w{wid}",
                    translation_en=f"word {wid}",
                    cefr_level="A1",
                    frequency_rank=wid,
                )
            )
        session.flush()

        sim = Simulator(PRESETS["average"])
        # parallel per-(user, word) simulator memory, keyed alongside the DB card
        mem: dict[tuple[int, int], MemoryState] = {}
        last_day: dict[tuple[int, int], float] = {}

        for uid in range(1, n_users + 1):
            # seed every word once (a "new" review) on day 0
            for wid in range(1, n_words + 1):
                _c, _rt, _p, st = sim.review(sim.initial_state(), 0.0, rng, first=True)
                mem[(uid, wid)] = st
                last_day[(uid, wid)] = 0.0
                scheduler.update_after_review(
                    session, uid, wid, correct=True, response_time_ms=2000, as_of=_EPOCH
                )

        for day in range(1, days + 1):
            as_of = _EPOCH + dt.timedelta(days=day)
            for uid in range(1, n_users + 1):
                due = scheduler.words_due_for_review(session, uid, as_of)
                for wid in due:
                    key = (uid, wid)
                    elapsed = day - last_day[key]
                    correct, rt, _true_p, mem[key] = sim.review(mem[key], elapsed, rng)
                    last_day[key] = float(day)
                    scheduler.update_after_review(
                        session, uid, wid, correct=correct, response_time_ms=rt, as_of=as_of
                    )

        rows = session.query(ReviewLog).filter(ReviewLog.source == "review").all()
        outcomes = [1 if r.correct else 0 for r in rows]

    return {
        "n_review_logs": len(outcomes),
        "recall_accuracy": round(recall_accuracy(outcomes), 4),
        "config": {"n_users": n_users, "n_words": n_words, "days": days, "seed": seed},
    }
