"""read_models: hydration + user profile projection."""

import datetime as dt

import pytest

from backend.core import read_models
from backend.core.scheduler import (
    create_learning_session,
    update_after_review,
    weak_words,
)
from backend.db.models import ReviewLog

from .conftest import T0

DAY = dt.timedelta(days=1)


def test_load_word_views_preserves_order_and_drops_unknown(session):
    views = read_models.load_word_views(session, [3, 1, 999, 2])
    assert [v.id for v in views] == [3, 1, 2]
    assert views[0].lemma == "wort3" and views[0].topic == "food"


def test_load_word_views_empty(session):
    assert read_models.load_word_views(session, []) == []


def test_user_profile_for_fresh_user(session):
    p = read_models.get_user_profile(session, 1, as_of=T0)
    assert p.user_id == 1
    assert p.target == "general"
    assert p.cefr_ceiling == "A1"
    assert (p.total_reviews, p.words_seen, p.words_due_now) == (0, 0, 0)
    assert p.overall_accuracy is None


def test_user_profile_after_some_reviews(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0)
    update_after_review(session, 1, 2, correct=False, response_time_ms=9000, as_of=T0)
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0 + DAY)

    p = read_models.get_user_profile(session, 1, as_of=T0 + 2 * DAY)
    assert p.total_reviews == 3
    assert p.words_seen == 2
    assert p.overall_accuracy == pytest.approx(2 / 3, abs=1e-4)
    assert p.cefr_ceiling == "A2"  # word 1 (A1) answered correctly
    # word 1: 2nd pass -> interval 6d -> due T0+7d (not yet). word 2: failed -> due T0+1d.
    assert p.words_due_now == 1


def test_user_profile_unknown_user_raises(session):
    with pytest.raises(LookupError):
        read_models.get_user_profile(session, 999)


def test_card_state_view_serialises_datetimes(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0)
    view = read_models.card_state_view(session, 1, 1)
    assert view.repetitions == 1
    assert view.last_reviewed == T0.isoformat()
    assert view.due_at == (T0 + DAY).isoformat()


def test_weak_words_orders_by_ease_then_accuracy(session):
    # word 1: two failures -> low ease. word 2: one failure. word 3: all correct.
    for when in (T0, T0 + DAY):
        update_after_review(session, 1, 1, correct=False, response_time_ms=9000, as_of=when)
    update_after_review(session, 1, 2, correct=False, response_time_ms=9000, as_of=T0)
    update_after_review(session, 1, 3, correct=True, response_time_ms=500, as_of=T0)

    assert weak_words(session, 1, limit=10)[:2] == [1, 2]
    assert 3 not in weak_words(session, 1, limit=2)


def test_weak_words_limit_zero(session):
    update_after_review(session, 1, 1, correct=False, response_time_ms=9000, as_of=T0)
    assert weak_words(session, 1, 0) == []
    assert session.query(ReviewLog).count() == 1


def test_pick_distractors_same_level_nearest_frequency(session):
    # fixture: 40 words, ranks 1..40, ten per band. word 5 is A1 (ranks 1..10).
    distractors = read_models.pick_distractors(session, 5, k=3)
    assert len(distractors) == 3
    assert "word 5" not in distractors  # never the answer itself
    # nearest ranks to 5 within A1: 4, 6, 3 (|Δ| 1,1,2), tie broken by id
    assert distractors == ["word 4", "word 6", "word 3"]


def test_pick_distractors_unknown_word(session):
    assert read_models.pick_distractors(session, 999) == []


def test_vocab_overview(session):
    ov = read_models.vocab_overview(session)
    assert ov["total"] == 40
    assert ov["by_cefr_level"] == {"A1": 10, "A2": 10, "B1": 10, "B2": 10}
    assert ov["by_topic"]["food"] == 3
    assert "vocab://word/{lemma}" in ov["resource_templates"]


def test_words_by_cefr_is_frequency_ordered_and_validates(session):
    a2 = read_models.words_by_cefr(session, "a2")  # case-insensitive
    assert [w.id for w in a2] == list(range(11, 21))
    with pytest.raises(ValueError):
        read_models.words_by_cefr(session, "C1")


def test_word_by_lemma_case_insensitive(session):
    assert read_models.word_by_lemma(session, "WORT7").id == 7
    assert read_models.word_by_lemma(session, "nope") is None


def test_session_view_hydrates_plan(session):
    update_after_review(session, 1, 1, correct=True, response_time_ms=800, as_of=T0)
    plan = create_learning_session(session, 1, 10, None, as_of=T0 + 5 * DAY)
    view = read_models.session_view(session, plan)
    assert view.session_id == plan.session_id
    assert view.user_id == 1
    assert [w.id for w in view.review_words] == plan.review_word_ids
    assert [w.id for w in view.new_words] == plan.new_word_ids
    assert all(isinstance(w.lemma, str) for w in view.review_words + view.new_words)
