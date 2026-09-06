"""The ``card_states`` cache stays consistent with a from-scratch log replay,
and backfills itself when it is behind (post-migration / repair)."""

import datetime as dt

from sqlalchemy import delete, select

from backend.core import scheduler
from backend.core.scheduler import replay, update_after_review, words_due_for_review
from backend.db.models import CardState as CardStateRow
from backend.db.models import ReviewLog

from .conftest import T0

DAY = dt.timedelta(days=1)


def _replayed(session, user_id, word_id):
    logs = session.scalars(
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id, ReviewLog.word_id == word_id)
        .order_by(ReviewLog.timestamp, ReviewLog.id)
    ).all()
    return replay(logs)


def test_row_matches_replay_after_each_review(session):
    for i, correct in enumerate([True, True, False, True]):
        update_after_review(
            session, 1, 5, correct=correct, response_time_ms=900, as_of=T0 + i * DAY
        )
        want = _replayed(session, 1, 5)
        row = session.get(CardStateRow, (1, 5))
        assert row is not None
        assert (row.repetitions, row.interval_days) == (want.repetitions, want.interval_days)
        assert row.ease_factor == want.ease_factor
        assert row.reviews == i + 1


def test_due_list_uses_the_cache_and_matches_replay(session):
    update_after_review(session, 1, 1, correct=False, response_time_ms=9000, as_of=T0)  # due +1d
    update_after_review(session, 1, 2, correct=True, response_time_ms=800, as_of=T0)  # due +1d
    update_after_review(session, 1, 2, correct=True, response_time_ms=800, as_of=T0 + DAY)  # +6d

    as_of = T0 + 2 * DAY
    got = words_due_for_review(session, 1, as_of)
    want = sorted(
        wid
        for wid in (1, 2, 3)
        if (st := _replayed(session, 1, wid)).last_reviewed and st.is_due(scheduler._as_utc(as_of))
    )
    assert got == want == [1]


def test_backfill_when_cache_is_missing(session):
    update_after_review(session, 1, 4, correct=True, response_time_ms=800, as_of=T0)
    update_after_review(session, 1, 9, correct=False, response_time_ms=9000, as_of=T0)
    # simulate a DB migrated to 0003 but not yet backfilled
    session.execute(delete(CardStateRow))
    session.flush()

    n = scheduler.rebuild_user_card_states(session, 1)
    assert n == 2
    assert session.scalar(select(CardStateRow.word_id).where(CardStateRow.word_id == 9)) == 9

    # and the read paths self-heal without an explicit rebuild
    session.execute(delete(CardStateRow))
    session.flush()
    assert 9 in words_due_for_review(session, 1, T0 + DAY)


def test_weak_words_orders_by_ease_then_accuracy(session):
    update_after_review(session, 1, 6, correct=False, response_time_ms=9000, as_of=T0)  # low ease
    update_after_review(session, 1, 7, correct=True, response_time_ms=800, as_of=T0)  # high ease
    assert scheduler.weak_words(session, 1, 5)[:2] == [6, 7]
