"""SQLAlchemy ORM models.

Mirrors the data model sketch in CLAUDE.md section 5. Kept deliberately small.
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
    ForeignKey,
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
    # IPA transcription, or a reference/URL to generated audio. See section 6.
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

    user: Mapped[User] = relationship(back_populates="review_logs")
    word: Mapped[Word] = relationship(back_populates="review_logs")


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
