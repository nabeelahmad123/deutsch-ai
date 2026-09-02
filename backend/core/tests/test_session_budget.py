"""Unit tests for the deterministic time-budget logic. No DB, no network."""

from backend.core.session_budget import (
    MAX_NEW_WORDS_PER_SESSION,
    SECONDS_PER_NEW_WORD,
    SECONDS_PER_REVIEW,
    plan_budget,
)


def test_zero_or_negative_minutes_yields_empty_budget():
    for minutes in (0, -5):
        b = plan_budget(minutes, due_review_count=10, available_new_count=10)
        assert (b.review_slots, b.new_slots, b.total_slots) == (0, 0, 0)


def test_all_time_to_new_words_when_nothing_due():
    b = plan_budget(10, due_review_count=0, available_new_count=50)
    assert b.review_slots == 0
    # 600s / 20s = 30, capped at MAX_NEW_WORDS_PER_SESSION
    assert b.new_slots == MAX_NEW_WORDS_PER_SESSION


def test_all_time_to_reviews_when_no_new_words_available():
    b = plan_budget(5, due_review_count=100, available_new_count=0)
    assert b.new_slots == 0
    assert b.review_slots == int((5 * 60) // SECONDS_PER_REVIEW)


def test_split_between_review_and_new():
    b = plan_budget(10, due_review_count=100, available_new_count=100)
    assert b.review_slots > 0 and b.new_slots > 0
    spent = b.review_slots * SECONDS_PER_REVIEW + b.new_slots * SECONDS_PER_NEW_WORD
    assert spent <= 10 * 60


def test_never_exceeds_supply():
    b = plan_budget(60, due_review_count=3, available_new_count=2)
    assert b.review_slots == 3
    assert b.new_slots == 2


def test_deterministic():
    kwargs = dict(due_review_count=17, available_new_count=9)
    assert plan_budget(12, **kwargs) == plan_budget(12, **kwargs)


def test_leftover_review_time_reclaimed_for_new_words():
    # Few reviews due; the unused review share should spill into new words.
    b = plan_budget(20, due_review_count=2, available_new_count=50)
    assert b.review_slots == 2
    assert b.new_slots == MAX_NEW_WORDS_PER_SESSION
