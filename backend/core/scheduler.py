"""Deterministic SM-2 scheduler.

No LLM calls and no network calls except the DB, here or in anything this module
imports -- ``tests/test_import_purity.py`` enforces it with an AST scan. Same
inputs, same outputs.

Per-card SM-2 state is not stored. It is reconstructed by folding ``sm2_update``
over the card's ``review_logs``, so ``update_after_review`` just appends a row.
``card_states`` is a derived cache of that fold, kept in sync incrementally and
rebuildable from the logs at any time.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from backend.core.session_budget import MAX_NEW_WORDS_PER_SESSION, plan_budget
from backend.db.models import CardState as CardStateRow
from backend.db.models import CEFRLevel, ReviewLog, ReviewSource, User, Word
from backend.db.models import Session as SessionRow

WordId = int

# CEFR bands, easiest first. A user's "ceiling" for new words is one band above
# the hardest band they have ever answered correctly (default A1, capped B2) --
# a deterministic heuristic, in the same approximate spirit as the frequency ->
# CEFR mapping.
_CEFR_ORDER: tuple[CEFRLevel, ...] = (
    CEFRLevel.A1,
    CEFRLevel.A2,
    CEFRLevel.B1,
    CEFRLevel.B2,
)

# --- SM-2 constants (Wozniak, SuperMemo 2) --------------------------------
MIN_EASE_FACTOR = 1.3
INITIAL_EASE_FACTOR = 2.5
FIRST_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6
PASS_QUALITY_THRESHOLD = 3  # q >= 3 counts as successful recall

# Deterministic (correct, latency) -> SM-2 grade 0..5. These thresholds are the
# single place to tune how much answer speed influences scheduling.
FAST_MS = 3_000
MEDIUM_MS = 8_000
QUALITY_CORRECT_FAST = 5
QUALITY_CORRECT_MEDIUM = 4
QUALITY_CORRECT_SLOW = 3
QUALITY_INCORRECT = 2


def quality_from_response(correct: bool, response_time_ms: int) -> int:
    """Map a graded answer to an SM-2 quality (0..5), deterministically."""
    if not correct:
        return QUALITY_INCORRECT
    rt = max(0, response_time_ms)
    if rt <= FAST_MS:
        return QUALITY_CORRECT_FAST
    if rt <= MEDIUM_MS:
        return QUALITY_CORRECT_MEDIUM
    return QUALITY_CORRECT_SLOW


@dataclass
class CardState:
    """Per (user, word) SM-2 state, reconstructed from review_logs."""

    repetitions: int = 0
    ease_factor: float = INITIAL_EASE_FACTOR
    interval_days: int = 0
    last_reviewed: dt.datetime | None = None

    def due_at(self) -> dt.datetime | None:
        if self.last_reviewed is None:
            return None
        return self.last_reviewed + dt.timedelta(days=self.interval_days)

    def is_due(self, as_of: dt.datetime) -> bool:
        due = self.due_at()
        return due is not None and due <= as_of


@dataclass
class SessionPlan:
    """A composed learning session (produced by ``build_session``).

    Named ``SessionPlan`` to avoid colliding with the ``sessions`` ORM model and
    SQLAlchemy's ``Session``.
    """

    user_id: int
    minutes_available: int
    topic: str | None
    review_word_ids: list[WordId] = field(default_factory=list)
    new_word_ids: list[WordId] = field(default_factory=list)
    session_id: int | None = None  # set once persisted by create_learning_session

    @property
    def word_ids(self) -> list[WordId]:
        return [*self.review_word_ids, *self.new_word_ids]


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Normalise a datetime to timezone-aware UTC.

    ``review_logs.timestamp`` is declared ``timezone=True`` but SQLite (and some
    round-trips) hand back naive values; treat those as UTC so due-date maths
    never mixes naive and aware datetimes.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _naive_utc(value: dt.datetime) -> dt.datetime:
    """UTC wall-clock with tzinfo stripped -- what we store in ``card_states`` so
    ``<=`` comparisons behave identically on SQLite and Postgres."""
    return _as_utc(value).replace(tzinfo=None)


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _ease_after(ease_factor: float, quality: int) -> float:
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    return max(MIN_EASE_FACTOR, ease_factor + delta)


def sm2_update(state: CardState, quality: int) -> CardState:
    """Apply one SM-2 review outcome (quality 0..5) and return the new state.

    Pure: does not mutate ``state`` and does not touch ``last_reviewed`` (the
    caller sets that from the log timestamp). The interval multiplier uses the
    ease factor from *before* this review, per the reference algorithm.
    """
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be 0..5, got {quality}")

    if quality < PASS_QUALITY_THRESHOLD:
        repetitions, interval = 0, FIRST_INTERVAL_DAYS
    elif state.repetitions == 0:
        repetitions, interval = 1, FIRST_INTERVAL_DAYS
    elif state.repetitions == 1:
        repetitions, interval = 2, SECOND_INTERVAL_DAYS
    else:
        repetitions = state.repetitions + 1
        interval = _round_half_up(state.interval_days * state.ease_factor)

    return replace(
        state,
        repetitions=repetitions,
        interval_days=interval,
        ease_factor=_ease_after(state.ease_factor, quality),
    )


def replay(logs: Iterable[ReviewLog]) -> CardState:
    """Fold SM-2 over a card's review history. ``logs`` must be chronological."""
    state = CardState()
    for log in logs:
        state = sm2_update(state, quality_from_response(log.correct, log.response_time_ms))
        state.last_reviewed = _as_utc(log.timestamp)
    return state


def _state_from_row(row: CardStateRow) -> CardState:
    return CardState(
        repetitions=row.repetitions,
        ease_factor=row.ease_factor,
        interval_days=row.interval_days,
        last_reviewed=_as_utc(row.last_reviewed) if row.last_reviewed else None,
    )


def _write_card_state(
    session: DbSession, user_id: int, word_id: WordId, state: CardState, logs: list[ReviewLog]
) -> CardStateRow:
    """Upsert the derived ``card_states`` row for one (user, word)."""
    row = session.get(CardStateRow, (user_id, word_id))
    if row is None:
        row = CardStateRow(user_id=user_id, word_id=word_id)
        session.add(row)
    row.repetitions = state.repetitions
    row.ease_factor = state.ease_factor
    row.interval_days = state.interval_days
    row.reviews = len(logs)
    row.correct_reviews = sum(1 for log in logs if log.correct)
    row.last_reviewed = _naive_utc(state.last_reviewed) if state.last_reviewed else None
    due = state.due_at()
    row.due_at = _naive_utc(due) if due else None
    return row


def _rebuild_one(session: DbSession, user_id: int, word_id: WordId) -> CardState:
    logs = list(
        session.scalars(
            select(ReviewLog)
            .where(ReviewLog.user_id == user_id, ReviewLog.word_id == word_id)
            .order_by(ReviewLog.timestamp, ReviewLog.id)
        )
    )
    state = replay(logs)
    if logs:
        _write_card_state(session, user_id, word_id, state, logs)
        session.flush()
    return state


def rebuild_user_card_states(session: DbSession, user_id: int) -> int:
    """Rebuild every ``card_states`` row for a user from ``review_logs``. Used to
    backfill after the 0003 migration and as a repair hook."""
    by_word = _logs_by_word(session, user_id)
    for word_id, logs in by_word.items():
        _write_card_state(session, user_id, word_id, replay(logs), logs)
    session.flush()
    return len(by_word)


def ensure_user_card_states(session: DbSession, user_id: int) -> None:
    """Lazily backfill a user's derived state if it is behind the logs (e.g. rows
    written before the 0003 migration).

    Memoised per ``Session`` (``session.info``) so a request that touches several
    card_states readers -- the dashboard hits five -- pays the check once. Safe:
    nothing desyncs the cache mid-session except ``update_after_review``, which
    maintains it, and an explicit ``rebuild_user_card_states``."""
    checked: set[int] = session.info.setdefault("_card_states_checked", set())
    if user_id in checked:
        return
    checked.add(user_id)
    logged = session.scalar(
        select(func.count(func.distinct(ReviewLog.word_id))).where(ReviewLog.user_id == user_id)
    )
    have = session.scalar(
        select(func.count()).select_from(CardStateRow).where(CardStateRow.user_id == user_id)
    )
    if (logged or 0) > (have or 0):
        rebuild_user_card_states(session, user_id)


def get_card_state(session: DbSession, user_id: int, word_id: WordId) -> CardState:
    row = session.get(CardStateRow, (user_id, word_id))
    if row is not None:
        return _state_from_row(row)
    return _rebuild_one(session, user_id, word_id)


def _logs_by_word(session: DbSession, user_id: int) -> dict[int, list[ReviewLog]]:
    """All of a user's review logs, grouped by word id, chronological within."""
    logs = session.scalars(
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.word_id, ReviewLog.timestamp, ReviewLog.id)
    ).all()
    grouped: dict[int, list[ReviewLog]] = {}
    for log in logs:
        grouped.setdefault(log.word_id, []).append(log)
    return grouped


def words_due_for_review(session: DbSession, user_id: int, as_of: dt.datetime) -> list[WordId]:
    """Word ids whose SM-2 due date is on or before ``as_of``, most overdue
    first then word id. Reads the ``card_states`` cache (indexed); new words
    (no history) never appear -- they go through ``select_new_words``.
    """
    ensure_user_card_states(session, user_id)
    cutoff = _naive_utc(as_of)
    rows = session.execute(
        select(CardStateRow.word_id, CardStateRow.due_at)
        .where(
            CardStateRow.user_id == user_id,
            CardStateRow.due_at.is_not(None),
            CardStateRow.due_at <= cutoff,
        )
        .order_by(CardStateRow.due_at, CardStateRow.word_id)
    )
    return [word_id for word_id, _due in rows]


def weak_words(session: DbSession, user_id: int, limit: int) -> list[WordId]:
    """The user's most fragile seen words, weakest first: lowest SM-2 ease
    factor, then lowest historical accuracy, then word id. Reads ``card_states``.
    """
    if limit <= 0:
        return []
    ensure_user_card_states(session, user_id)
    accuracy = CardStateRow.correct_reviews * 1.0 / func.nullif(CardStateRow.reviews, 0)
    rows = session.scalars(
        select(CardStateRow.word_id)
        .where(CardStateRow.user_id == user_id, CardStateRow.reviews > 0)
        .order_by(CardStateRow.ease_factor, accuracy, CardStateRow.word_id)
        .limit(limit)
    )
    return list(rows)


def update_after_review(
    session: DbSession,
    user_id: int,
    word_id: WordId,
    correct: bool,
    response_time_ms: int,
    *,
    as_of: dt.datetime | None = None,
    error_type: str | None = None,
) -> None:
    """Record one review outcome as a ``review_logs`` row.

    State is derived from the logs, so there is nothing else to persist. The
    row's ``source`` is ``new`` on the card's first ever review, else ``review``.
    ``error_type`` is an optional diagnostic label (grading.diagnose) stored as-is
    -- it does not affect scheduling. ``as_of`` defaults to now; the simulator and
    tests pass it explicitly for determinism. The caller controls the transaction.

    Raises ``LookupError`` for an unknown user or word (SQLite does not enforce
    the foreign keys, so guard explicitly).
    """
    if session.get(User, user_id) is None:
        raise LookupError(f"no user with id {user_id}")
    if session.get(Word, word_id) is None:
        raise LookupError(f"no word with id {word_id}")
    seen_before = session.scalar(
        select(ReviewLog.id)
        .where(ReviewLog.user_id == user_id, ReviewLog.word_id == word_id)
        .limit(1)
    )
    session.add(
        ReviewLog(
            user_id=user_id,
            word_id=word_id,
            timestamp=_as_utc(as_of or dt.datetime.now(dt.UTC)),
            correct=correct,
            response_time_ms=max(0, response_time_ms),
            source=ReviewSource.review if seen_before else ReviewSource.new,
            error_type=error_type if not correct else None,
        )
    )
    session.flush()
    # Refresh the derived state for this one word (cheap: a card has few logs).
    _rebuild_one(session, user_id, word_id)


def cefr_ceiling(session: DbSession, user_id: int) -> CEFRLevel:
    """Highest CEFR band the user may see as *new* words.

    One band above the hardest band they have answered correctly, capped at B2;
    A1 for a user with no correct reviews yet.
    """
    passed = session.scalars(
        select(Word.cefr_level)
        .join(ReviewLog, ReviewLog.word_id == Word.id)
        .where(ReviewLog.user_id == user_id, ReviewLog.correct.is_(True))
        .distinct()
    ).all()
    if not passed:
        return CEFRLevel.A1
    hardest = max(_CEFR_ORDER.index(level) for level in passed)
    return _CEFR_ORDER[min(hardest + 1, len(_CEFR_ORDER) - 1)]


def select_new_words(
    session: DbSession,
    user_id: int,
    topic: str | None,
    n: int,
    *,
    level: CEFRLevel | None = None,
) -> list[WordId]:
    """The ``n`` most frequent words the user has never seen, optionally
    restricted to ``topic``. Frequency-ordered, deterministic.

    ``level`` pins the CEFR band to study explicitly (a learner choice from the
    UI); without it, words are drawn from every band up to the learner's derived
    ``cefr_ceiling``.
    """
    if n <= 0:
        return []
    if level is not None:
        allowed = (level,)
    else:
        allowed = _CEFR_ORDER[: _CEFR_ORDER.index(cefr_ceiling(session, user_id)) + 1]
    seen = select(ReviewLog.word_id).where(ReviewLog.user_id == user_id)
    stmt = select(Word.id).where(Word.cefr_level.in_(allowed), Word.id.not_in(seen))
    if topic is not None:
        stmt = stmt.where(Word.topic == topic)
    stmt = stmt.order_by(Word.frequency_rank, Word.id).limit(n)
    return list(session.scalars(stmt))


def build_session(
    session: DbSession,
    user_id: int,
    minutes_available: int,
    topic: str | None,
    *,
    level: CEFRLevel | None = None,
    as_of: dt.datetime | None = None,
) -> SessionPlan:
    """Compose a session: time-budget the minutes (``plan_budget``), then fill
    the review slots from due words and the new slots from ``select_new_words``.

    Review and new lists are disjoint by construction (a "new" word has no review
    history). ``level`` pins the CEFR band for new words. Deterministic for a
    fixed ``as_of``.
    """
    as_of = as_of or dt.datetime.now(dt.UTC)
    due = words_due_for_review(session, user_id, as_of)
    new_candidates = select_new_words(
        session, user_id, topic, MAX_NEW_WORDS_PER_SESSION, level=level
    )
    # An unrecognised or exhausted topic ("exam", "general", a niche subject with
    # no tagged words) should not yield an empty session -- fall back to no topic
    # filter rather than hand back nothing.
    if topic is not None and not new_candidates:
        new_candidates = select_new_words(
            session, user_id, None, MAX_NEW_WORDS_PER_SESSION, level=level
        )

    budget = plan_budget(
        minutes_available,
        due_review_count=len(due),
        available_new_count=len(new_candidates),
    )
    return SessionPlan(
        user_id=user_id,
        minutes_available=minutes_available,
        topic=topic,
        review_word_ids=due[: budget.review_slots],
        new_word_ids=new_candidates[: budget.new_slots],
    )


def create_learning_session(
    session: DbSession,
    user_id: int,
    minutes_available: int,
    topic: str | None,
    *,
    level: CEFRLevel | None = None,
    as_of: dt.datetime | None = None,
) -> SessionPlan:
    """``build_session`` plus a persisted ``sessions`` row; returns the plan with
    ``session_id`` populated. Raises ``LookupError`` for an unknown user."""
    if session.get(User, user_id) is None:
        raise LookupError(f"no user with id {user_id}")
    plan = build_session(session, user_id, minutes_available, topic, level=level, as_of=as_of)
    row = SessionRow(
        user_id=user_id,
        duration_minutes_requested=minutes_available,
        words_covered=0,
        topic=topic,
    )
    session.add(row)
    session.flush()
    plan.session_id = row.id
    return plan


def finish_session(session: DbSession, session_id: int, words_covered: int) -> SessionRow:
    """Record how many words a session ended up covering. Raises ``LookupError``
    if the session id is unknown."""
    row = session.get(SessionRow, session_id)
    if row is None:
        raise LookupError(f"no session with id {session_id}")
    row.words_covered = max(0, words_covered)
    session.flush()
    return row


__all__ = [
    "CardState",
    "SessionPlan",
    "WordId",
    "finish_session",
    "build_session",
    "cefr_ceiling",
    "create_learning_session",
    "ensure_user_card_states",
    "get_card_state",
    "plan_budget",
    "quality_from_response",
    "rebuild_user_card_states",
    "replay",
    "select_new_words",
    "sm2_update",
    "update_after_review",
    "weak_words",
    "words_due_for_review",
]
