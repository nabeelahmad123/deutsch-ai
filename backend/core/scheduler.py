"""Deterministic scheduler -- SM-2 baseline.

CONTRACT (CLAUDE.md section 7). No LLM calls, no network calls except the DB, in
this file or anything it imports. Given the same inputs it must always return the
same outputs (non-negotiable principle #1).

Per-card SM-2 state is NOT stored -- it is reconstructed by folding ``sm2_update``
over the card's ``review_logs`` (data model, section 5). ``update_after_review``
therefore just appends a log row.

Build-order step 2. LG-04 covers state + updates (``sm2_update``, ``replay``,
``get_card_state``, ``words_due_for_review``, ``update_after_review``); word
selection and session composition land in LG-05.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from backend.core.session_budget import MAX_NEW_WORDS_PER_SESSION, plan_budget
from backend.db.models import CEFRLevel, ReviewLog, ReviewSource, Word

WordId = int

# CEFR bands, easiest first. A user's "ceiling" for new words is one band above
# the hardest band they have ever answered correctly (default A1, capped B2) --
# a deterministic heuristic, in the same approximate spirit as the frequency ->
# CEFR mapping (CLAUDE.md section 6).
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
    """A composed learning session (produced by ``build_session``, LG-05).

    Named ``SessionPlan`` to avoid colliding with the ``sessions`` ORM model and
    SQLAlchemy's ``Session``; section 7 calls it ``Session`` illustratively.
    """

    user_id: int
    minutes_available: int
    topic: str | None
    review_word_ids: list[WordId] = field(default_factory=list)
    new_word_ids: list[WordId] = field(default_factory=list)

    @property
    def word_ids(self) -> list[WordId]:
        return [*self.review_word_ids, *self.new_word_ids]


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
        state.last_reviewed = log.timestamp
    return state


def get_card_state(session: DbSession, user_id: int, word_id: WordId) -> CardState:
    logs = session.scalars(
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id, ReviewLog.word_id == word_id)
        .order_by(ReviewLog.timestamp, ReviewLog.id)
    ).all()
    return replay(logs)


def words_due_for_review(session: DbSession, user_id: int, as_of: dt.datetime) -> list[WordId]:
    """Word ids whose reconstructed due date is on or before ``as_of``.

    Ordered by due date (most overdue first), then word id. New words (no review
    history) are never "due" -- they are handled by ``select_new_words``.
    """
    logs = session.scalars(
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.word_id, ReviewLog.timestamp, ReviewLog.id)
    ).all()

    by_word: dict[int, list[ReviewLog]] = {}
    for log in logs:
        by_word.setdefault(log.word_id, []).append(log)

    due: list[tuple[dt.datetime, int]] = []
    for word_id, word_logs in by_word.items():
        state = replay(word_logs)
        if state.is_due(as_of):
            due.append((state.due_at(), word_id))

    due.sort(key=lambda pair: (pair[0], pair[1]))
    return [word_id for _due_at, word_id in due]


def update_after_review(
    session: DbSession,
    user_id: int,
    word_id: WordId,
    correct: bool,
    response_time_ms: int,
    *,
    as_of: dt.datetime | None = None,
) -> None:
    """Record one review outcome as a ``review_logs`` row.

    State is derived from the logs, so there is nothing else to persist. The
    row's ``source`` is ``new`` on the card's first ever review, else ``review``.
    ``as_of`` defaults to now; the simulator and tests pass it explicitly for
    determinism. The caller controls the transaction (this only flushes).
    """
    seen_before = session.scalar(
        select(ReviewLog.id)
        .where(ReviewLog.user_id == user_id, ReviewLog.word_id == word_id)
        .limit(1)
    )
    session.add(
        ReviewLog(
            user_id=user_id,
            word_id=word_id,
            timestamp=as_of or dt.datetime.now(dt.UTC),
            correct=correct,
            response_time_ms=max(0, response_time_ms),
            source=ReviewSource.review if seen_before else ReviewSource.new,
        )
    )
    session.flush()


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


def select_new_words(session: DbSession, user_id: int, topic: str | None, n: int) -> list[WordId]:
    """The ``n`` most frequent words the user has never seen, within their CEFR
    ceiling, optionally restricted to ``topic``. Frequency-ordered, deterministic.
    """
    if n <= 0:
        return []
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
    as_of: dt.datetime | None = None,
) -> SessionPlan:
    """Compose a session: time-budget the minutes (``plan_budget``), then fill
    the review slots from due words and the new slots from ``select_new_words``.

    Review and new lists are disjoint by construction (a "new" word has no review
    history). Deterministic for a fixed ``as_of``.
    """
    as_of = as_of or dt.datetime.now(dt.UTC)
    due = words_due_for_review(session, user_id, as_of)
    new_candidates = select_new_words(session, user_id, topic, MAX_NEW_WORDS_PER_SESSION)

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


__all__ = [
    "CardState",
    "SessionPlan",
    "WordId",
    "build_session",
    "cefr_ceiling",
    "get_card_state",
    "plan_budget",
    "quality_from_response",
    "replay",
    "select_new_words",
    "sm2_update",
    "update_after_review",
    "words_due_for_review",
]
