"""Read-only projections for the MCP tool layer.

MCP tool bodies call only ``backend.core`` (scheduler for decisions, this module
for hydration/profile). Deterministic given ``as_of``; no LLM, DB access only --
same rules as ``scheduler.py`` (CLAUDE.md section 7).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from backend.core.scheduler import (
    SessionPlan,
    cefr_ceiling,
    get_card_state,
    words_due_for_review,
)
from backend.db.models import ReviewLog, User, Word

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
