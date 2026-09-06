"""Read-only projections for the MCP tool layer.

MCP tool bodies call only ``backend.core`` (scheduler for decisions, this module
for hydration/profile). Deterministic given ``as_of``; no LLM, DB access only --
same rules as ``scheduler.py`` (CLAUDE.md section 7).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from backend.core.scheduler import (
    SessionPlan,
    _as_utc,
    _naive_utc,
    cefr_ceiling,
    ensure_user_card_states,
    finish_session,
    get_card_state,
    words_due_for_review,
)
from backend.db.models import CardState as CardStateRow
from backend.db.models import ReviewLog, User, Word
from backend.db.models import Session as SessionRow

# Frozen dataclasses: the MCP layer publishes these directly as typed tool
# output (mcp converts a dataclass return annotation into a JSON schema).


@dataclass(frozen=True)
class WordView:
    id: int
    lemma: str
    article: str | None
    plural: str | None
    translation_en: str
    cefr_level: str
    topic: str | None
    ipa_or_audio_ref: str | None


@dataclass(frozen=True)
class CardStateView:
    word_id: int
    repetitions: int
    ease_factor: float
    interval_days: int
    last_reviewed: str | None
    due_at: str | None


@dataclass(frozen=True)
class UserProfile:
    user_id: int
    target: str
    created_at: str | None
    cefr_ceiling: str
    total_reviews: int
    words_seen: int
    words_due_now: int
    overall_accuracy: float | None


@dataclass(frozen=True)
class SessionView:
    session_id: int | None
    user_id: int
    minutes_available: int
    topic: str | None
    review_words: list[WordView]
    new_words: list[WordView]


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    user_id: int
    topic: str | None
    minutes_requested: int
    words_covered: int


@dataclass(frozen=True)
class MistakeItem:
    lemma: str
    article: str | None
    plural: str | None
    translation_en: str
    cefr_level: str
    topic: str | None
    error_type: str | None
    at: str | None


@dataclass(frozen=True)
class MistakeSummary:
    total_reviews: int
    total_misses: int
    by_error_type: dict[str, int]
    recent_misses: list[MistakeItem]


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def load_word_views(session: DbSession, word_ids: list[int]) -> list[WordView]:
    """Hydrate word ids to views, preserving the given order, dropping unknowns."""
    if not word_ids:
        return []
    by_id = {w.id: w for w in session.scalars(select(Word).where(Word.id.in_(word_ids))).all()}
    views = []
    for word_id in word_ids:
        w = by_id.get(word_id)
        if w is not None:
            views.append(
                WordView(
                    id=w.id,
                    lemma=w.lemma,
                    article=w.article,
                    plural=w.plural,
                    translation_en=w.translation_en,
                    cefr_level=str(w.cefr_level),
                    topic=w.topic,
                    ipa_or_audio_ref=w.ipa_or_audio_ref,
                )
            )
    return views


def pick_distractors(session: DbSession, word_id: int, k: int = 3) -> list[str]:
    """Plausible wrong translations for a multiple-choice question: other words
    at the same CEFR level, nearest by frequency rank. Deterministic."""
    word = session.get(Word, word_id)
    if word is None:
        return []
    rows = session.scalars(
        select(Word.translation_en)
        .where(Word.cefr_level == word.cefr_level, Word.id != word_id)
        .order_by(func.abs(Word.frequency_rank - word.frequency_rank), Word.id)
        .limit(k)
    ).all()
    return list(rows)


def session_view(session: DbSession, plan: SessionPlan) -> SessionView:
    return SessionView(
        session_id=plan.session_id,
        user_id=plan.user_id,
        minutes_available=plan.minutes_available,
        topic=plan.topic,
        review_words=load_word_views(session, plan.review_word_ids),
        new_words=load_word_views(session, plan.new_word_ids),
    )


def summarise_session(session: DbSession, session_id: int, words_covered: int) -> SessionSummary:
    row = finish_session(session, session_id, words_covered)
    return SessionSummary(
        session_id=row.id,
        user_id=row.user_id,
        topic=row.topic,
        minutes_requested=row.duration_minutes_requested,
        words_covered=row.words_covered,
    )


# --- vocab resource projections (LG-08) --------------------------------------

_CEFR_LEVELS = ("A1", "A2", "B1", "B2")
VOCAB_RESOURCE_TEMPLATES = ("vocab://words/{cefr_level}", "vocab://word/{lemma}")


def vocab_overview(session: DbSession) -> dict:
    """Shape of the vocab table: totals, breakdowns, and how to read slices."""
    total = session.scalar(select(func.count()).select_from(Word)) or 0
    by_cefr = {
        str(level): count
        for level, count in session.execute(
            select(Word.cefr_level, func.count()).group_by(Word.cefr_level)
        )
    }
    by_topic = {
        topic: count
        for topic, count in session.execute(
            select(Word.topic, func.count())
            .where(Word.topic.is_not(None))
            .group_by(Word.topic)
            .order_by(func.count().desc())
        )
    }
    return {
        "total": total,
        "by_cefr_level": {lvl: by_cefr.get(lvl, 0) for lvl in _CEFR_LEVELS},
        "by_topic": by_topic,
        "resource_templates": list(VOCAB_RESOURCE_TEMPLATES),
        "note": "CEFR level is approximated from frequency band (CLAUDE.md section 6).",
    }


def words_by_cefr(session: DbSession, cefr_level: str) -> list[WordView]:
    level = cefr_level.strip().upper()
    if level not in _CEFR_LEVELS:
        raise ValueError(f"cefr_level must be one of {_CEFR_LEVELS}, got {cefr_level!r}")
    ids = session.scalars(
        select(Word.id).where(Word.cefr_level == level).order_by(Word.frequency_rank)
    ).all()
    return load_word_views(session, list(ids))


def mistake_summary(session: DbSession, user_id: int, *, limit: int = 60) -> MistakeSummary:
    """Recent incorrect answers with their diagnostic labels, for the agent's
    mistake-pattern analysis. Aggregate counts + a bounded sample of the misses
    (newest first), each carrying the word's forms so the LLM can spot patterns
    (e.g. gender errors clustered on feminine nouns)."""
    total = (
        session.scalar(
            select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user_id)
        )
        or 0
    )
    by_type = {
        (etype or "unlabelled"): n
        for etype, n in session.execute(
            select(ReviewLog.error_type, func.count())
            .where(ReviewLog.user_id == user_id, ReviewLog.correct.is_(False))
            .group_by(ReviewLog.error_type)
        )
    }
    rows = session.execute(
        select(
            Word.lemma,
            Word.article,
            Word.plural,
            Word.translation_en,
            Word.cefr_level,
            Word.topic,
            ReviewLog.error_type,
            ReviewLog.timestamp,
        )
        .join(Word, ReviewLog.word_id == Word.id)
        .where(ReviewLog.user_id == user_id, ReviewLog.correct.is_(False))
        .order_by(ReviewLog.timestamp.desc(), ReviewLog.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    recent = [
        MistakeItem(
            lemma=r.lemma,
            article=r.article,
            plural=r.plural,
            translation_en=r.translation_en,
            cefr_level=str(r.cefr_level),
            topic=r.topic,
            error_type=r.error_type,
            at=_iso(r.timestamp),
        )
        for r in rows
    ]
    return MistakeSummary(
        total_reviews=total,
        total_misses=sum(by_type.values()),
        by_error_type=by_type,
        recent_misses=recent,
    )


def coverage_by_level(session: DbSession, user_id: int) -> list[dict]:
    """Per-CEFR-band vocabulary coverage for one learner: how many words exist,
    how many they have seen at least once, and how many they have answered
    correctly at least once. Ordered A1 -> B2.
    """

    def _counts(stmt) -> dict[str, int]:
        return {str(level): count for level, count in session.execute(stmt)}

    totals = _counts(select(Word.cefr_level, func.count()).group_by(Word.cefr_level))
    base = (
        select(Word.cefr_level, func.count(func.distinct(ReviewLog.word_id)))
        .join(ReviewLog, ReviewLog.word_id == Word.id)
        .where(ReviewLog.user_id == user_id)
        .group_by(Word.cefr_level)
    )
    seen = _counts(base)
    known = _counts(base.where(ReviewLog.correct.is_(True)))
    return [
        {
            "level": lvl,
            "total": totals.get(lvl, 0),
            "seen": seen.get(lvl, 0),
            "known": known.get(lvl, 0),
        }
        for lvl in _CEFR_LEVELS
    ]


def word_by_lemma(session: DbSession, lemma: str) -> WordView | None:
    word = session.scalar(select(Word).where(func.lower(Word.lemma) == lemma.strip().lower()))
    if word is None:
        return None
    return load_word_views(session, [word.id])[0]


def card_state_view(session: DbSession, user_id: int, word_id: int) -> CardStateView:
    state = get_card_state(session, user_id, word_id)
    due = state.due_at()
    return CardStateView(
        word_id=word_id,
        repetitions=state.repetitions,
        ease_factor=round(state.ease_factor, 4),
        interval_days=state.interval_days,
        last_reviewed=_iso(state.last_reviewed),
        due_at=_iso(due),
    )


def get_user_profile(
    session: DbSession, user_id: int, *, as_of: dt.datetime | None = None
) -> UserProfile:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"no user with id {user_id}")

    as_of = as_of or dt.datetime.now(dt.UTC)
    total = (
        session.scalar(
            select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user_id)
        )
        or 0
    )
    correct = (
        session.scalar(
            select(func.count())
            .select_from(ReviewLog)
            .where(ReviewLog.user_id == user_id, ReviewLog.correct.is_(True))
        )
        or 0
    )
    seen = (
        session.scalar(
            select(func.count(func.distinct(ReviewLog.word_id))).where(ReviewLog.user_id == user_id)
        )
        or 0
    )
    return UserProfile(
        user_id=user_id,
        target=str(user.target),
        created_at=_iso(user.created_at),
        cefr_ceiling=str(cefr_ceiling(session, user_id)),
        total_reviews=total,
        words_seen=seen,
        words_due_now=len(words_due_for_review(session, user_id, as_of)),
        overall_accuracy=round(correct / total, 4) if total else None,
    )


# --- dashboard projections ------------------------------------------------
# Read-only analytics for the frontend's Progress/Dashboard tab. Same rules as
# the rest of this module: deterministic given ``as_of``, DB only, no LLM.

_DAY = dt.timedelta(days=1)


def _user_logs(session: DbSession, user_id: int) -> list[ReviewLog]:
    return list(
        session.scalars(
            select(ReviewLog)
            .where(ReviewLog.user_id == user_id)
            .order_by(ReviewLog.timestamp, ReviewLog.id)
        )
    )


def daily_activity(
    session: DbSession, user_id: int, *, days: int = 30, as_of: dt.datetime | None = None
) -> list[dict]:
    """Reviews (and how many were correct) per day for the last ``days`` days,
    oldest first, with zero-fill for days with no activity."""
    today = _as_utc(as_of or dt.datetime.now(dt.UTC)).date()
    start = today - dt.timedelta(days=days - 1)
    counts: dict[dt.date, list[int]] = {}
    for log in _user_logs(session, user_id):
        d = _as_utc(log.timestamp).date()
        if d < start:
            continue
        bucket = counts.setdefault(d, [0, 0])
        bucket[0] += 1
        bucket[1] += 1 if log.correct else 0
    out = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        n, c = counts.get(d, (0, 0))
        out.append({"date": d.isoformat(), "reviews": n, "correct": c})
    return out


def study_streak(
    session: DbSession, user_id: int, *, as_of: dt.datetime | None = None
) -> dict[str, int]:
    """Current and best run of consecutive calendar days with >=1 review. The
    current streak stays alive if the last review was today or yesterday."""
    today = _as_utc(as_of or dt.datetime.now(dt.UTC)).date()
    active = sorted({_as_utc(log.timestamp).date() for log in _user_logs(session, user_id)})
    if not active:
        return {"current": 0, "best": 0}

    best = run = 1
    for prev, cur in zip(active, active[1:], strict=False):
        run = run + 1 if cur - prev == _DAY else 1
        best = max(best, run)

    current = 0
    if active[-1] in (today, today - _DAY):
        current = 1
        for prev, cur in zip(reversed(active), list(reversed(active))[1:], strict=False):
            if prev - cur == _DAY:
                current += 1
            else:
                break
    return {"current": current, "best": best}


def coverage_by_topic(session: DbSession, user_id: int, *, limit: int = 12) -> list[dict]:
    """Per-topic coverage (total / seen / known), biggest topics first."""

    def _counts(stmt) -> dict[str, int]:
        return {topic: n for topic, n in session.execute(stmt) if topic is not None}

    totals = _counts(
        select(Word.topic, func.count()).where(Word.topic.is_not(None)).group_by(Word.topic)
    )
    base = (
        select(Word.topic, func.count(func.distinct(ReviewLog.word_id)))
        .join(ReviewLog, ReviewLog.word_id == Word.id)
        .where(ReviewLog.user_id == user_id, Word.topic.is_not(None))
        .group_by(Word.topic)
    )
    seen = _counts(base)
    known = _counts(base.where(ReviewLog.correct.is_(True)))
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [
        {"topic": t, "total": n, "seen": seen.get(t, 0), "known": known.get(t, 0)}
        for t, n in ranked
    ]


def maturity_breakdown(session: DbSession, user_id: int) -> dict[str, int]:
    """Seen words bucketed by how well established they are (SM-2 interval):
    learning (< 7d or never passed), young (7-20d), mature (>= 21d).

    Reads ``card_states``; callers other than ``build_dashboard`` should
    ``ensure_user_card_states`` first (``build_dashboard`` does)."""
    out = {"learning": 0, "young": 0, "mature": 0}
    for reps, interval in session.execute(
        select(CardStateRow.repetitions, CardStateRow.interval_days).where(
            CardStateRow.user_id == user_id
        )
    ):
        if reps == 0 or interval < 7:
            out["learning"] += 1
        elif interval < 21:
            out["young"] += 1
        else:
            out["mature"] += 1
    return out


def review_forecast(
    session: DbSession, user_id: int, *, as_of: dt.datetime | None = None
) -> list[dict]:
    """How many seen words fall due in each window ahead. Each word counted once.

    Reads ``card_states`` (see ``maturity_breakdown`` note on backfill)."""
    now = _naive_utc(as_of or dt.datetime.now(dt.UTC))
    end_today = dt.datetime.combine(now.date(), dt.time.max)
    edges = [
        ("overdue", now),
        ("today", end_today),
        ("next 7 days", now + 7 * _DAY),
        ("next 30 days", now + 30 * _DAY),
    ]
    buckets = dict.fromkeys([label for label, _ in edges] + ["later"], 0)
    for (due,) in session.execute(
        select(CardStateRow.due_at).where(
            CardStateRow.user_id == user_id, CardStateRow.due_at.is_not(None)
        )
    ):
        for label, edge in edges:
            if due <= edge:
                buckets[label] += 1
                break
        else:
            buckets["later"] += 1
    return [{"label": label, "count": buckets[label]} for label in [*buckets]]


def recent_sessions(session: DbSession, user_id: int, *, limit: int = 8) -> list[dict]:
    rows = session.scalars(
        select(SessionRow)
        .where(SessionRow.user_id == user_id)
        .order_by(SessionRow.started_at.desc(), SessionRow.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "started_at": _iso(r.started_at),
            "minutes": r.duration_minutes_requested,
            "words_covered": r.words_covered,
            "topic": r.topic,
        }
        for r in rows
    ]


def build_dashboard(session: DbSession, user_id: int, *, as_of: dt.datetime | None = None) -> dict:
    """Everything the Dashboard tab needs, in one call."""
    as_of = as_of or dt.datetime.now(dt.UTC)
    profile = get_user_profile(session, user_id, as_of=as_of)  # raises LookupError if unknown
    ensure_user_card_states(session, user_id)  # once for all the card_states readers below
    user = session.get(User, user_id)
    streak = study_streak(session, user_id, as_of=as_of)
    levels = coverage_by_level(session, user_id)
    due_ids = words_due_for_review(session, user_id, as_of)[:20]
    from backend.core.scheduler import weak_words

    weak_ids = weak_words(session, user_id, 10)
    return {
        "user_id": user_id,
        "username": user.username if user else None,
        "target": profile.target,
        "cefr_ceiling": profile.cefr_ceiling,
        "total_reviews": profile.total_reviews,
        "words_seen": profile.words_seen,
        "words_due_now": profile.words_due_now,
        "words_known": sum(row["known"] for row in levels),
        "overall_accuracy": profile.overall_accuracy,
        "current_streak": streak["current"],
        "best_streak": streak["best"],
        "daily_activity": daily_activity(session, user_id, as_of=as_of),
        "by_level": levels,
        "by_topic": coverage_by_topic(session, user_id),
        "maturity": maturity_breakdown(session, user_id),
        "forecast": review_forecast(session, user_id, as_of=as_of),
        "recent_sessions": recent_sessions(session, user_id),
        "due_words": [asdict(w) for w in load_word_views(session, due_ids)],
        "weak_words": [asdict(w) for w in load_word_views(session, weak_ids)],
    }
