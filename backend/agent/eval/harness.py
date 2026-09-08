"""Score the agent's output for one eval case, and run the whole suite live."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable

from backend.agent.eval.cases import CASES, CaseScore, EvalCase
from backend.agent.orchestrator import SessionRequest, run_session
from backend.core.session_budget import SECONDS_PER_NEW_WORD, SECONDS_PER_REVIEW

# "Fits the budget" = the session's estimated time cost, under the scheduler's
# own per-item constants, is within 25% of the minutes asked for. Reviews are
# cheap (~8s), so a review backlog legitimately packs many items into a short
# session -- this checks time, not a flat word count.
_BUDGET_SLACK = 1.25


def score_case(
    case: EvalCase,
    *,
    stopped: str,
    intent: dict,
    tool_calls: list[str],
    review_ids: set[int],
    new_ids: set[int],
    due_ids: set[int],
    seen_ids: set[int],
) -> CaseScore:
    """Pure scoring -- no network, no DB. Everything it needs is passed in."""
    notes: list[str] = []

    minutes = intent.get("minutes_available")
    if case.expect_minutes is None:
        intent_minutes_ok = isinstance(minutes, int) and minutes > 0
        if not intent_minutes_ok:
            notes.append(f"no sane minutes chosen (got {minutes!r})")
    else:
        intent_minutes_ok = (
            isinstance(minutes, int) and abs(minutes - case.expect_minutes) <= case.minutes_tol
        )
        if not intent_minutes_ok:
            notes.append(f"minutes {minutes!r}, expected ~{case.expect_minutes}")

    topic = intent.get("topic") or None
    if case.expect_topic is None:
        intent_topic_ok = topic in (None, "general")
        if not intent_topic_ok:
            notes.append(f"invented topic {topic!r}")
    else:
        intent_topic_ok = topic == case.expect_topic
        if not intent_topic_ok:
            notes.append(f"topic {topic!r}, expected {case.expect_topic!r}")

    missing = [t for t in case.must_call if t not in tool_calls]
    forbidden = [t for t in case.must_not_call if t in tool_calls]
    compose_count = tool_calls.count("create_learning_session")
    tools_ok = not missing and not forbidden and compose_count == 1
    if missing:
        notes.append(f"never called {missing}")
    if forbidden:
        notes.append(f"called forbidden {forbidden}")
    if compose_count != 1:
        notes.append(f"create_learning_session called {compose_count}x")

    n_words = len(review_ids) + len(new_ids)
    budget_s = max(1, (case.expect_minutes or minutes or 10)) * 60
    est_s = len(review_ids) * SECONDS_PER_REVIEW + len(new_ids) * SECONDS_PER_NEW_WORD
    over_budget = est_s > budget_s * _BUDGET_SLACK
    session_ok = (
        stopped == "completed"
        and n_words > 0
        and review_ids.issubset(due_ids)  # no phantom review words
        and new_ids.isdisjoint(seen_ids)  # "new" really is unseen
        and review_ids.isdisjoint(new_ids)
        and not over_budget
    )
    if stopped != "completed":
        notes.append(f"stopped={stopped}")
    elif not n_words:
        notes.append("composed an empty session")
    else:
        if not review_ids.issubset(due_ids):
            notes.append(f"{len(review_ids - due_ids)} review words are not actually due")
        if not new_ids.isdisjoint(seen_ids):
            notes.append(f"{len(new_ids & seen_ids)} 'new' words were already seen")
        if not review_ids.isdisjoint(new_ids):
            notes.append("review/new word lists overlap")
        if over_budget:
            notes.append(
                f"{n_words} words (~{est_s / 60:.0f} min of work) for a "
                f"{budget_s // 60}-min budget"
            )

    return CaseScore(
        id=case.id,
        text=case.text,
        stopped=stopped,
        expect_minutes=case.expect_minutes,
        expect_topic=case.expect_topic,
        got_minutes=minutes if isinstance(minutes, int) else None,
        got_topic=topic,
        tool_calls=tool_calls,
        intent_minutes_ok=intent_minutes_ok,
        intent_topic_ok=intent_topic_ok,
        tools_ok=tools_ok,
        session_ok=session_ok,
        notes=notes,
    )


# --- live runner ---------------------------------------------------------


def _seed_temp_db() -> None:
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tempfile.mkdtemp()}/eval.db"
    from backend.db import seed as db_seed
    from backend.db import session as db_session

    db_seed.upgrade_to_head()
    db_session.configure(os.environ["DATABASE_URL"], force=True)
    db_seed.seed_from_sql(db_seed.SEED_SQL)


def _seed_user_history(user_id: int) -> None:
    """Give the eval user real review history so the session-sanity checks bite:
    without a due list and a seen set, "review words are due" and "new words are
    unseen" would both be vacuously true."""
    import datetime as dt

    from backend.core import scheduler
    from backend.db.session import get_session

    past = _now() - dt.timedelta(days=12)
    with next(get_session()) as s:  # type: ignore[call-overload]
        for i, wid in enumerate(range(1, 19)):  # 18 A1/A2 words
            scheduler.update_after_review(
                s, user_id, wid, correct=(i % 3 != 0), response_time_ms=1500, as_of=past
            )
        s.commit()


def run_suite(
    *, model: str | None = None, cases: Iterable[EvalCase] = CASES, user_id: int = 1
) -> list[CaseScore]:
    """Run the real agent on every case against a seeded DB where the user has
    12-day-old review history (so ~all of it is due now). Needs an Anthropic key.
    The planning loop never records reviews, so seen/due stay stable across
    cases."""
    _seed_temp_db()
    _seed_user_history(user_id)
    from backend.core import scheduler
    from backend.db.models import ReviewLog
    from backend.db.session import get_session

    scores: list[CaseScore] = []
    for case in cases:
        result = run_session(SessionRequest(raw_text=case.text, user_id=user_id), model=model)
        with next(get_session()) as s:  # type: ignore[call-overload]
            seen_ids = {
                r.word_id for r in s.query(ReviewLog).filter(ReviewLog.user_id == user_id).all()
            }
            due_ids = set(scheduler.words_due_for_review(s, user_id, _now()))
        scores.append(
            score_case(
                case,
                stopped=result.stopped,
                intent=result.intent,
                tool_calls=result.tool_calls,
                review_ids={w["id"] for w in result.review_words},
                new_ids={w["id"] for w in result.new_words},
                due_ids=due_ids,
                seen_ids=seen_ids,
            )
        )
    return scores


def _now():
    import datetime as dt

    return dt.datetime.now(dt.UTC)
