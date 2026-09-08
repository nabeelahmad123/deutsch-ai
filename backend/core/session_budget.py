"""Time-budget -> item-count logic for a study session.

Deterministic and dependency-free. Given
a number of minutes, decide how many review items and how many new words fit,
and how to split the time between them.

Timing constants are rough averages; they are the single place to tune session
pacing. A review is quicker than learning a new word.
"""

from __future__ import annotations

from dataclasses import dataclass

SECONDS_PER_REVIEW = 8.0
SECONDS_PER_NEW_WORD = 20.0
# Fraction of the budget spent on reviews when both are available. Reviews are
# retention-critical, so they get the larger share.
REVIEW_TIME_SHARE = 0.6
MAX_NEW_WORDS_PER_SESSION = 15


@dataclass(frozen=True)
class SessionBudget:
    minutes: int
    review_slots: int
    new_slots: int

    @property
    def total_slots(self) -> int:
        return self.review_slots + self.new_slots


def plan_budget(
    minutes_available: int,
    *,
    due_review_count: int,
    available_new_count: int,
) -> SessionBudget:
    """Return how many review and new items to schedule for the session.

    Never schedules more reviews than are due, nor more new words than are
    available or than ``MAX_NEW_WORDS_PER_SESSION``. If there is nothing due,
    the whole budget goes to new words (and vice versa).
    """
    if minutes_available <= 0:
        return SessionBudget(minutes=0, review_slots=0, new_slots=0)

    total_seconds = minutes_available * 60
    due_review_count = max(0, due_review_count)
    available_new_count = max(0, available_new_count)

    if due_review_count == 0:
        review_seconds, new_seconds = 0.0, total_seconds
    elif available_new_count == 0:
        review_seconds, new_seconds = total_seconds, 0.0
    else:
        review_seconds = total_seconds * REVIEW_TIME_SHARE
        new_seconds = total_seconds - review_seconds

    review_slots = min(due_review_count, int(review_seconds // SECONDS_PER_REVIEW))
    new_slots = min(
        available_new_count,
        MAX_NEW_WORDS_PER_SESSION,
        int(new_seconds // SECONDS_PER_NEW_WORD),
    )

    # Reclaim time unused by one bucket for the other.
    spent = review_slots * SECONDS_PER_REVIEW + new_slots * SECONDS_PER_NEW_WORD
    leftover = total_seconds - spent
    if leftover >= SECONDS_PER_REVIEW and review_slots < due_review_count:
        extra = int(leftover // SECONDS_PER_REVIEW)
        review_slots = min(due_review_count, review_slots + extra)
    elif leftover >= SECONDS_PER_NEW_WORD and new_slots < min(
        available_new_count, MAX_NEW_WORDS_PER_SESSION
    ):
        extra = int(leftover // SECONDS_PER_NEW_WORD)
        new_slots = min(available_new_count, MAX_NEW_WORDS_PER_SESSION, new_slots + extra)

    return SessionBudget(minutes=minutes_available, review_slots=review_slots, new_slots=new_slots)
