"""Deterministic scheduler -- SM-2 baseline.

CONTRACT (CLAUDE.md section 7). No LLM calls, no network calls except the DB, in
this file or anything it imports. Given the same inputs it must always return the
same outputs (non-negotiable principle #1).

Day-1 status: signatures and the SM-2 update math are stubbed. Full
implementation + >90% unit coverage is build-order step 2.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from backend.core.session_budget import plan_budget

WordId = int

# SM-2 constants (Wozniak). EF floor is 1.3.
MIN_EASE_FACTOR = 1.3
INITIAL_EASE_FACTOR = 2.5
FIRST_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6


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


@dataclass
class Session:
    user_id: int
    minutes_available: int
    topic: str | None
    review_word_ids: list[WordId] = field(default_factory=list)
    new_word_ids: list[WordId] = field(default_factory=list)

    @property
    def word_ids(self) -> list[WordId]:
        return [*self.review_word_ids, *self.new_word_ids]


def sm2_update(state: CardState, quality: int, *, now: dt.datetime) -> CardState:
    """Apply one SM-2 review outcome. ``quality`` is 0-5.

    TODO(step 2): full SM-2 recurrence + property tests.
    """
    raise NotImplementedError("sm2_update lands in build-order step 2")


def words_due_for_review(user_id: int, as_of: dt.datetime) -> list[WordId]:
    raise NotImplementedError("words_due_for_review lands in build-order step 2")


def update_after_review(
    user_id: int, word_id: WordId, correct: bool, response_time_ms: int
) -> None:
    raise NotImplementedError("update_after_review lands in build-order step 2")


def select_new_words(user_id: int, topic: str | None, n: int) -> list[WordId]:
    raise NotImplementedError("select_new_words lands in build-order step 2")


def build_session(user_id: int, minutes_available: int, topic: str | None) -> Session:
    """Compose a session: budget the time, then fill review + new slots.

    The time-budget half (``plan_budget``) is already implemented and tested;
    the word-selection half is stubbed until step 2.
    """
    raise NotImplementedError("build_session lands in build-order step 2; see plan_budget()")


__all__ = [
    "CardState",
    "Session",
    "WordId",
    "build_session",
    "plan_budget",
    "select_new_words",
    "sm2_update",
    "update_after_review",
    "words_due_for_review",
]
