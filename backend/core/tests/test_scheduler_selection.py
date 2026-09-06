"""select_new_words / cefr_ceiling / build_session against the SQLite fixture."""

import datetime as dt

import pytest

from backend.core.scheduler import (
    build_session,
    cefr_ceiling,
    create_learning_session,
    select_new_words,
    update_after_review,
)
from backend.core.session_budget import MAX_NEW_WORDS_PER_SESSION
from backend.db.models import CEFRLevel, ReviewLog
from backend.db.models import Session as SessionRow

from .conftest import T0

DAY = dt.timedelta(days=1)


def test_new_user_ceiling_is_a1_and_only_a1_words(session):
    assert cefr_ceiling(session, 1) == CEFRLevel.A1
    picked = select_new_words(session, 1, topic=None, n=5)
    assert picked == [1, 2, 3, 4, 5]  # frequency-ordered A1 words


def test_ceiling_rises_one_band_above_hardest_passed(session):
    update_after_review(session, 1, 5, correct=True, response_time_ms=800, as_of=T0)  # A1
    assert cefr_ceiling(session, 1) == CEFRLevel.A2

    update_after_review(session, 1, 15, correct=True, response_time_ms=800, as_of=T0)  # A2
    assert cefr_ceiling(session, 1) == CEFRLevel.B1


def test_wrong_answers_do_not_raise_the_ceiling(session):
    update_after_review(session, 1, 15, correct=False, response_time_ms=9000, as_of=T0)
    assert cefr_ceiling(session, 1) == CEFRLevel.A1


def test_select_new_words_excludes_seen_and_respects_topic(session):
    update_after_review(session, 1, 3, correct=True, response_time_ms=800, as_of=T0)
    # ceiling is now A2; word 3 (food) is seen, words 7 & 15 (food) are not
    assert select_new_words(session, 1, topic="food", n=10) == [7, 15]


def test_select_new_words_n_zero_or_negative(session):
    assert select_new_words(session, 1, topic=None, n=0) == []
    assert select_new_words(session, 1, topic=None, n=-3) == []


def test_explicit_level_pins_the_band_and_ignores_the_ceiling(session):
    # a brand-new user's ceiling is A1, but an explicit B1 request gets B1 words
    picked = select_new_words(session, 1, topic=None, n=5, level=CEFRLevel.B1)
    assert picked == [21, 22, 23, 24, 25]  # B1 band, frequency-ordered

    plan = build_session(session, 1, minutes_available=30, topic=None, level=CEFRLevel.B1, as_of=T0)
    assert plan.new_word_ids and all(21 <= wid <= 30 for wid in plan.new_word_ids)


def test_build_session_splits_budget_between_due_and_new(session):
    # Two due words: reviewed on day 0, due day 1; ask on day 5.
    for wid in (1, 2):
        update_after_review(session, 1, wid, correct=True, response_time_ms=800, as_of=T0)
    plan = build_session(session, 1, minutes_available=10, topic=None, as_of=T0 + 5 * DAY)

    assert plan.review_word_ids == [1, 2]
    assert 0 < len(plan.new_word_ids) <= MAX_NEW_WORDS_PER_SESSION
    assert set(plan.review_word_ids).isdisjoint(plan.new_word_ids)
    assert len(plan.word_ids) == len(set(plan.word_ids))
    # seen words (1, 2) must never appear as "new"
    assert 1 not in plan.new_word_ids and 2 not in plan.new_word_ids


def test_build_session_all_new_when_nothing_due(session):
    plan = build_session(session, 1, minutes_available=5, topic=None, as_of=T0)
    assert plan.review_word_ids == []
    assert plan.new_word_ids  # A1 words
    assert plan.new_word_ids == sorted(plan.new_word_ids)  # frequency-ordered ids


def test_build_session_zero_minutes_is_empty(session):
    plan = build_session(session, 1, minutes_available=0, topic=None, as_of=T0)
    assert plan.word_ids == []


def test_build_session_is_deterministic(session):
    kwargs = dict(minutes_available=12, topic=None, as_of=T0 + 3 * DAY)
    a = build_session(session, 1, **kwargs)
    b = build_session(session, 1, **kwargs)
    assert a == b


def test_create_learning_session_persists_a_row_with_session_id(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0)
    plan = create_learning_session(session, 1, minutes_available=10, topic=None, as_of=T0 + 5 * DAY)
    assert plan.session_id is not None
    row = session.get(SessionRow, plan.session_id)
    assert row.user_id == 1
    assert row.duration_minutes_requested == 10
    assert row.words_covered == 0


def test_create_learning_session_unknown_user_raises(session):
    with pytest.raises(LookupError):
        create_learning_session(session, 999, minutes_available=10, topic=None, as_of=T0)


def test_review_and_new_counts_never_exceed_supply(session):
    # only one due word, huge time budget
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0)
    plan = build_session(session, 1, minutes_available=600, topic=None, as_of=T0 + 10 * DAY)
    assert plan.review_word_ids == [1]
    assert len(plan.new_word_ids) <= MAX_NEW_WORDS_PER_SESSION
    total_new_available = session.query(ReviewLog).count()  # sanity: logs exist
    assert total_new_available == 1
