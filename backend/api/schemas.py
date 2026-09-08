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


class WordPage(BaseModel):
    """A page of words plus the total matching the filters (for a frontend)."""

    total: int
    limit: int
    offset: int
    items: list[WordOut]


class TopicCount(BaseModel):
    topic: str
    count: int


class UserIn(BaseModel):
    target: UserTarget = UserTarget.general


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: dt.datetime
    target: UserTarget
    username: str | None = None


_USERNAME = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class RegisterIn(BaseModel):
    username: str = _USERNAME
    password: str = Field(min_length=4, max_length=128)
    target: UserTarget = UserTarget.general


class LoginIn(BaseModel):
    username: str = _USERNAME
    password: str = Field(min_length=1, max_length=128)


class AuthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
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
    error_type: str | None = None


# --- study flow (minimal frontend, CLAUDE.md section 13) --------------------


class SessionIn(BaseModel):
    user_id: int
    minutes_available: int = Field(ge=1, le=120)
    topic: str | None = None
    cefr_level: CEFRLevel | None = None  # pin new words to one band; None = auto


class SessionOut(BaseModel):
    session_id: int | None
    user_id: int
    minutes_available: int
    topic: str | None
    review_words: list[dict]
    new_words: list[dict]


class AgentPlanIn(BaseModel):
    """A natural-language request for the agent (LLM tool-use loop, MCP tools)."""

    user_id: int = Field(ge=1)
    request: str = Field(min_length=3, max_length=400)
    mode: str = Field(default="plan", pattern="^(plan|converse)$")


class AgentPlanOut(BaseModel):
    mode: str
    stopped: str  # completed | no_session | max_turns | refusal
    turns: int
    reply: str
    intent: dict = Field(default_factory=dict)
    tool_calls: list[str] = Field(default_factory=list)
    servers_used: list[str] = Field(default_factory=list)
    session_id: int | None = None
    review_words: list[dict] = Field(default_factory=list)
    new_words: list[dict] = Field(default_factory=list)
    quiz: list[dict] = Field(default_factory=list)


class QuizIn(BaseModel):
    word_ids: list[int] = Field(min_length=1, max_length=50)
    quiz_type: str = "en_to_de"


class QuizQuestionOut(BaseModel):
    question_id: str
    word_id: int
    quiz_type: str
    prompt: str
    options: list[str] | None
    hint: str | None


class AnswerIn(BaseModel):
    user_id: int
    question_id: str
    user_answer: str = Field(max_length=200)


class AnswerOut(BaseModel):
    question_id: str
    word_id: int
    correct: bool
    score: float
    rationale: str
    expected: str
    method: str
    error_type: str | None = None  # why it was wrong (grading.ERROR_TYPES)
    feedback: str = ""  # one learner-facing sentence
    new_state: dict


class ConversationIn(BaseModel):
    user_id: int
    scenario: str = Field(min_length=2, max_length=40)
    minutes: int = Field(default=10, ge=1, le=60)


class ConversationStartOut(BaseModel):
    session_id: int
    scenario: str
    level: str
    opener: str
    targets: list[dict]


class ConvMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=4000)


class TurnIn(BaseModel):
    session_id: int
    user_id: int
    scenario: str = Field(min_length=2, max_length=40)
    target_word_ids: list[int] = Field(min_length=1, max_length=15)
    history: list[ConvMessage] = Field(default_factory=list, max_length=40)
    user_message: str = Field(min_length=1, max_length=2000)


class TurnOut(BaseModel):
    reply: str
    used_word_ids: list[int]
    available: bool


class ConvFinishIn(BaseModel):
    session_id: int
    user_id: int
    used_word_ids: list[int] = Field(default_factory=list, max_length=15)
    turns: int = Field(ge=0, le=200)


class ReviewIn(BaseModel):
    """A self-graded flashcard outcome (the swipe deck has no typed answer)."""

    user_id: int
    word_id: int
    correct: bool
    response_time_ms: int = Field(default=5000, ge=0, le=600_000)


class ReviewOut(BaseModel):
    word_id: int
    correct: bool
    new_state: dict


class FinishIn(BaseModel):
    words_covered: int = Field(ge=0, le=1000)


class ProgressOut(BaseModel):
    user_id: int
    target: str
    cefr_ceiling: str
    total_reviews: int
    words_seen: int
    words_due_now: int
    overall_accuracy: float | None
    by_level: list[dict]  # per CEFR band: {level, total, seen, known}
    due_words: list[dict]
    weak_words: list[dict]
