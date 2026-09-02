"""Pydantic request/response schemas for the API. Kept separate from ORM models."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from backend.db.models import CEFRLevel, ReviewSource, UserTarget


class WordIn(BaseModel):
    lemma: str = Field(min_length=1, max_length=128)
    article: str | None = Field(default=None, max_length=8)
    plural: str | None = Field(default=None, max_length=128)
    translation_en: str = Field(min_length=1, max_length=256)
    cefr_level: CEFRLevel
    frequency_rank: int = Field(ge=1)
    topic: str | None = Field(default=None, max_length=64)
    ipa_or_audio_ref: str | None = None


class WordOut(WordIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class UserIn(BaseModel):
    target: UserTarget = UserTarget.general


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: dt.datetime
    target: UserTarget


class ReviewLogIn(BaseModel):
    user_id: int
    word_id: int
    correct: bool
    response_time_ms: int = Field(ge=0)
    source: ReviewSource


class ReviewLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    word_id: int
    timestamp: dt.datetime
    correct: bool
    response_time_ms: int
    source: ReviewSource
