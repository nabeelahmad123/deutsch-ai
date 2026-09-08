"""SQLAlchemy ORM models.

Mirrors the data model sketch in docs/DESIGN.md. Kept deliberately small.
No LLM or network imports here; this module is safe to import from
``backend/core`` and from the ingestion scripts.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CEFRLevel(enum.StrEnum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"


class UserTarget(enum.StrEnum):
    work = "work"
    travel = "travel"
    general = "general"
    exam = "exam"


class ReviewSource(enum.StrEnum):
    review = "review"
    new = "new"


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    lemma: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Article for nouns ("der"/"die"/"das"); NULL for non-nouns.
    article: Mapped[str | None] = mapped_column(String(8))
    plural: Mapped[str | None] = mapped_column(String(128))
    translation_en: Mapped[str] = mapped_column(String(256))
    cefr_level: Mapped[CEFRLevel] = mapped_column(Enum(CEFRLevel, name="cefr_level"), index=True)
    frequency_rank: Mapped[int] = mapped_column(Integer, index=True)
    topic: Mapped[str | None] = mapped_column(String(64), index=True)
    # IPA transcription, or a reference/URL to generated audio.
    ipa_or_audio_ref: Mapped[str | None] = mapped_column(Text)

    review_logs: Mapped[list[ReviewLog]] = relationship(back_populates="word")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    target: Mapped[UserTarget] = mapped_column(
        Enum(UserTarget, name="user_target"), default=UserTarget.general
    )
    # Optional lightweight identity. NULL for anonymous users (the agent, the
    # simulator, tests): login is an extra way to reach a user_id, not a gate on
    # the data layer. Set together by POST /auth/register.
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(256))

    review_logs: Mapped[list[ReviewLog]] = relationship(back_populates="user")
    sessions: Mapped[list[Session]] = relationship(back_populates="user")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    correct: Mapped[bool] = mapped_column(Boolean)
    response_time_ms: Mapped[int] = mapped_column(Integer)
    source: Mapped[ReviewSource] = mapped_column(Enum(ReviewSource, name="review_source"))
    # Diagnostic label for an incorrect free-text answer (grading.ERROR_TYPES);
    # NULL for correct answers and for self-graded swipes.
    error_type: Mapped[str | None] = mapped_column(String(24))

    user: Mapped[User] = relationship(back_populates="review_logs")
    word: Mapped[Word] = relationship(back_populates="review_logs")


class CardState(Base):
    """Materialised SM-2 state per (user, word).

    ``review_logs`` remains the append-only source of truth; this table is a
    derived cache so hot reads (due list, weak list, dashboard) are indexed
    look-ups instead of replaying every log in Python on each request. It is
    updated incrementally by ``scheduler.update_after_review`` and can always be
    rebuilt from the logs (``scheduler.rebuild_user_card_states``).
    """

    __tablename__ = "card_states"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    reviews: Mapped[int] = mapped_column(Integer, default=0)
    correct_reviews: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Naive UTC (see scheduler._naive_utc) so SQLite/Postgres comparisons match.
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_card_states_user_due", "user_id", "due_at"),)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    duration_minutes_requested: Mapped[int] = mapped_column(Integer)
    words_covered: Mapped[int] = mapped_column(Integer, default=0)
    topic: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")
