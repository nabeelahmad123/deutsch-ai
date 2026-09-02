"""Scheduler state reconstruction + due logic against a SQLite fixture DB."""

import datetime as dt

import pytest

from backend.core.scheduler import (
    get_card_state,
    update_after_review,
    words_due_for_review,
)
from backend.db.models import ReviewLog

from .conftest import T0

DAY = dt.timedelta(days=1)


def _log(session, word_id, *, correct, rt, when):
    session.add(
        ReviewLog(
            user_id=1,
            word_id=word_id,
            timestamp=when,
            correct=correct,
            response_time_ms=rt,
            source="review",
        )
    )
    session.flush()


def test_new_word_has_empty_state(session):
    state = get_card_state(session, 1, 1)
    assert state.repetitions == 0
    assert state.last_reviewed is None
    assert state.due_at() is None


def test_state_is_reconstructed_from_logs(session):
    _log(session, 1, correct=True, rt=1000, when=T0)
    _log(session, 1, correct=True, rt=1000, when=T0 + DAY)

    state = get_card_state(session, 1, 1)
    assert state.repetitions == 2
    assert state.interval_days == 6
    assert state.last_reviewed == T0 + DAY
    assert state.due_at() == T0 + DAY + 6 * DAY


def test_words_due_for_review_filters_by_as_of(session):
    _log(session, 1, correct=True, rt=1000, when=T0)  # due T0 + 1d
    _log(session, 2, correct=True, rt=1000, when=T0 + 2 * DAY)  # due T0 + 3d

    assert words_due_for_review(session, 1, T0 + 2 * DAY) == [1]
    assert words_due_for_review(session, 1, T0) == []
    assert set(words_due_for_review(session, 1, T0 + 10 * DAY)) == {1, 2}


def test_words_due_ordered_most_overdue_first(session):
    _log(session, 3, correct=True, rt=1000, when=T0 + 5 * DAY)  # due T0 + 6d
    _log(session, 1, correct=True, rt=1000, when=T0)  # due T0 + 1d
    _log(session, 2, correct=True, rt=1000, when=T0 + DAY)  # due T0 + 2d

    assert words_due_for_review(session, 1, T0 + 30 * DAY) == [1, 2, 3]


def test_failed_review_makes_word_due_again_next_day(session):
    _log(session, 1, correct=True, rt=1000, when=T0)
    _log(session, 1, correct=True, rt=1000, when=T0 + DAY)  # interval now 6d
    _log(session, 1, correct=False, rt=9000, when=T0 + 2 * DAY)  # reset -> 1d

    state = get_card_state(session, 1, 1)
    assert state.repetitions == 0
    assert state.interval_days == 1
    assert words_due_for_review(session, 1, T0 + 3 * DAY) == [1]


def test_update_after_review_appends_row_and_sets_source(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=1200, as_of=T0)
    update_after_review(session, 1, 1, correct=True, response_time_ms=1200, as_of=T0 + DAY)

    rows = session.query(ReviewLog).filter_by(word_id=1).order_by(ReviewLog.timestamp).all()
    assert [r.source for r in rows] == ["new", "review"]
    assert get_card_state(session, 1, 1).repetitions == 2


def test_update_after_review_clamps_negative_latency(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=-10, as_of=T0)
    assert session.query(ReviewLog).filter_by(word_id=1).one().response_time_ms == 0


def test_update_after_review_rejects_unknown_user_or_word(session):
    with pytest.raises(LookupError):
        update_after_review(session, 999, 1, correct=True, response_time_ms=500, as_of=T0)
    with pytest.raises(LookupError):
        update_after_review(session, 1, 999, correct=True, response_time_ms=500, as_of=T0)


def test_update_after_review_is_deterministic(session):
    for word_id in (1, 2):
        update_after_review(session, 1, word_id, correct=True, response_time_ms=500, as_of=T0)
        update_after_review(
            session, 1, word_id, correct=False, response_time_ms=12_000, as_of=T0 + DAY
        )
    assert get_card_state(session, 1, 1) == get_card_state(session, 1, 2)
