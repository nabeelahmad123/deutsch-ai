"""MCP server #1 -- learning tools + vocab resource.

Every tool is a thin wrapper: open a DB session, delegate to ``backend.core``
(scheduler for decisions, read_models for hydration/projection), return a typed
dataclass. No scheduling logic and no ad-hoc DB queries live here -- that is the
whole point of the tool layer. ``evaluate_answer`` is the one tool that may call
the LLM, for free-text semantic grading, with a fuzzy-match fallback.

Every tool call and every resource read is traced (name, input, output, latency,
success) via ``backend.tracing``.

The vocab table is also exposed as an MCP *resource* (``vocab://...``), not only
through tools -- part of the point of using MCP over plain function calling.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError, ToolError

from backend.core import read_models, scheduler
from backend.core.read_models import CardStateView, SessionView, UserProfile, WordView
from backend.db.models import Word
from backend.db.session import session_scope
from backend.study import conversation, quiz
from backend.study.grading import AnswerEvaluation, diagnose, grade
from backend.tracing.tracer import Tracer

INSTRUCTIONS = (
    "German vocabulary learning tools. A deterministic spaced-repetition core "
    "decides what to study; these tools only expose it. Typical flow: "
    "get_user_profile -> create_learning_session (or get_words_due_for_review / "
    "get_weak_words / get_new_words) -> create_quiz -> evaluate_answer -> "
    "update_learning_state after each answer. The vocab table is also readable as "
    "resources: vocab://words, vocab://words/{cefr_level}, vocab://word/{lemma}."
)

DEFAULT_DUE_LIMIT = 50
DEFAULT_WEAK_LIMIT = 10
DEFAULT_NEW_COUNT = 10
MAX_LIMIT = 200
NEUTRAL_RESPONSE_MS = 5_000  # used when a caller has no real latency to report
_TRACE_PREVIEW = 400  # chars of serialised output kept in a trace event


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clamp(value: int) -> int:
    return max(0, min(value, MAX_LIMIT))


def _preview(result: Any) -> Any:
    """Compact, JSON-safe summary of a tool/resource result for the trace log."""
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    if isinstance(result, list):
        return {"count": len(result), "first": _preview(result[0]) if result else None}
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return text if len(text) <= _TRACE_PREVIEW else text[:_TRACE_PREVIEW] + "..."


def build_server(*, tracer: Tracer | None = None) -> MCPServer:
    server = MCPServer("learning", instructions=INSTRUCTIONS)
    tracer = tracer or Tracer()

    def traced(kind: str) -> Callable[[Callable], Callable]:
        def decorate(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                name = f"learning.{kind}.{fn.__name__}"
                with tracer.trace_tool_call(name, kwargs or list(args)) as box:
                    result = fn(*args, **kwargs)
                    box["output"] = _preview(result)
                    return result

            return wrapper

        return decorate

    tool = traced("tool")
    resource = traced("resource")

    # --- read: profile + word selection --------------------------------------
    @server.tool()
    @tool
    def get_user_profile(user_id: int) -> UserProfile:
        """Where a learner stands: target, CEFR ceiling, totals, accuracy, due count."""
        with session_scope() as session:
            try:
                return read_models.get_user_profile(session, user_id, as_of=_now())
            except LookupError as exc:
                raise ToolError(str(exc)) from exc

    @server.tool()
    @tool
    def get_words_due_for_review(user_id: int, limit: int = DEFAULT_DUE_LIMIT) -> list[WordView]:
        """Words whose spaced-repetition interval has elapsed, most overdue first."""
        with session_scope() as session:
            ids = scheduler.words_due_for_review(session, user_id, _now())[: _clamp(limit)]
            return read_models.load_word_views(session, ids)

    @server.tool()
    @tool
    def get_weak_words(user_id: int, limit: int = DEFAULT_WEAK_LIMIT) -> list[WordView]:
        """The learner's most fragile seen words (lowest SM-2 ease factor first)."""
        with session_scope() as session:
            ids = scheduler.weak_words(session, user_id, _clamp(limit))
            return read_models.load_word_views(session, ids)

    @server.tool()
    @tool
    def get_mistake_summary(user_id: int, limit: int = 60) -> read_models.MistakeSummary:
        """Recent incorrect answers with their diagnostic labels (wrong_gender,
        spelling, false_friend, ...), plus counts by label. For analysing where a
        learner is going wrong."""
        with session_scope() as session:
            return read_models.mistake_summary(session, user_id, limit=_clamp(limit))

    @server.tool()
    @tool
    def get_new_words(
        user_id: int, topic: str | None = None, count: int = DEFAULT_NEW_COUNT
    ) -> list[WordView]:
        """Unseen words within the learner's CEFR ceiling, most frequent first."""
        with session_scope() as session:
            ids = scheduler.select_new_words(session, user_id, topic, _clamp(count))
            return read_models.load_word_views(session, ids)

    # --- session composition ----------------------------------------------
    @server.tool()
    @tool
    def create_learning_session(
        user_id: int, minutes_available: int, topic: str | None = None
    ) -> SessionView:
        """Compose (and persist) a session for the time available: due reviews +
        new words, split by a deterministic time budget."""
        with session_scope() as session:
            try:
                plan = scheduler.create_learning_session(
                    session, user_id, minutes_available, topic, as_of=_now()
                )
            except LookupError as exc:
                raise ToolError(str(exc)) from exc
            return read_models.session_view(session, plan)

    @server.tool()
    @tool
    def finish_learning_session(session_id: int, words_covered: int) -> read_models.SessionSummary:
        """Close out a session, recording how many words it covered."""
        with session_scope() as session:
            try:
                return read_models.summarise_session(session, session_id, words_covered)
            except LookupError as exc:
                raise ToolError(str(exc)) from exc

    @server.tool()
    @tool
    def create_conversation_session(
        user_id: int, scenario: str, minutes: int = 10
    ) -> conversation.ConversationStart:
        """Start a conversational-practice roleplay: pick target words (due +
        weak + a little new -- the scheduler still chooses them), persist a
        session, and return the tutor's German opening line. The dialogue itself
        runs turn-by-turn via the study API; call update_learning_state for each
        target word the learner ends up using correctly."""
        with session_scope() as session:
            try:
                return conversation.start_conversation(session, user_id, scenario, minutes)
            except LookupError as exc:
                raise ToolError(str(exc)) from exc

    # --- quiz + grading + state -----------------------------------------
    @server.tool()
    @tool
    def create_quiz(word_ids: list[int], quiz_type: str = "en_to_de") -> list[quiz.QuizQuestion]:
        """Build quiz questions for the given words. quiz_type: en_to_de,
        de_to_en, multiple_choice, article. Non-nouns are skipped for 'article'."""
        if quiz_type not in quiz.QUIZ_TYPES:
            raise ToolError(f"unknown quiz_type {quiz_type!r}; expected one of {quiz.QUIZ_TYPES}")
        with session_scope() as session:
            views = read_models.load_word_views(session, word_ids)
            questions = []
            for view in views:
                distractors = (
                    read_models.pick_distractors(session, view.id)
                    if quiz_type == "multiple_choice"
                    else None
                )
                question = quiz.build_question(view, quiz_type, distractors)
                if question is not None:
                    questions.append(question)
            return questions

    @server.tool()
    @tool
    def evaluate_answer(question_id: str, user_answer: str) -> AnswerEvaluation:
        """Grade an answer and diagnose why a miss happened. Free-text (de_to_en)
        uses the LLM for semantic grading, falling back to fuzzy matching; others
        are exact/fuzzy. ``error_type`` / ``feedback`` explain an incorrect
        answer (wrong_gender / wrong_plural / spelling / false_friend / ...)."""
        try:
            spec = quiz.decode_qid(question_id)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        result = grade(spec["t"], spec["r"], user_answer, prompt=spec.get("p", ""))
        with session_scope() as session:
            word = session.get(Word, spec["w"])
            article = word.article if word else None
            plural = word.plural if word else None
        diag = diagnose(
            spec["t"],
            spec["r"],
            user_answer,
            correct=result.correct,
            prompt=spec.get("p", ""),
            article=article,
            plural=plural,
        )
        return AnswerEvaluation(
            question_id=question_id,
            word_id=spec["w"],
            quiz_type=spec["t"],
            correct=result.correct,
            score=result.score,
            rationale=result.rationale,
            method=result.method,
            expected=spec["r"],
            error_type=diag.error_type,
            feedback=diag.feedback,
        )

    @server.tool()
    @tool
    def update_learning_state(
        user_id: int,
        word_id: int,
        correct: bool,
        response_time_ms: int = NEUTRAL_RESPONSE_MS,
        error_type: str | None = None,
    ) -> CardStateView:
        """Record a review outcome and return the word's new spaced-repetition
        state. ``error_type`` (from ``evaluate_answer``) is stored for analysis
        and does not affect scheduling."""
        with session_scope() as session:
            try:
                scheduler.update_after_review(
                    session,
                    user_id,
                    word_id,
                    correct,
                    response_time_ms,
                    as_of=_now(),
                    error_type=error_type,
                )
            except LookupError as exc:
                raise ToolError(str(exc)) from exc
            return read_models.card_state_view(session, user_id, word_id)

    # --- vocab resource -------------------------------------------------
    @server.resource("vocab://words", mime_type="application/json")
    @resource
    def vocab_index() -> str:
        """Overview of the vocabulary table: totals and breakdowns."""
        with session_scope() as session:
            return json.dumps(read_models.vocab_overview(session), ensure_ascii=False)

    @server.resource("vocab://words/{cefr_level}", mime_type="application/json")
    @resource
    def vocab_by_level(cefr_level: str) -> str:
        """Every word at a CEFR level (A1-B2), frequency-ordered."""
        with session_scope() as session:
            try:
                words = read_models.words_by_cefr(session, cefr_level)
            except ValueError as exc:
                raise ResourceError(str(exc)) from exc
            return json.dumps([asdict(w) for w in words], ensure_ascii=False)

    @server.resource("vocab://word/{lemma}", mime_type="application/json")
    @resource
    def vocab_word(lemma: str) -> str:
        """A single word by lemma (case-insensitive)."""
        with session_scope() as session:
            word = read_models.word_by_lemma(session, lemma)
            if word is None:
                raise ResourceNotFoundError(f"no word with lemma {lemma!r}")
            return json.dumps(asdict(word), ensure_ascii=False)

    return server
