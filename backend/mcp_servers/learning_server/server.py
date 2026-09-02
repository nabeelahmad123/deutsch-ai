"""MCP server #1 -- learning tools (CLAUDE.md section 8).

Every tool is a thin wrapper: open a DB session, delegate to ``backend.core``
(scheduler for decisions, read_models for hydration), return a typed dataclass.
No scheduling logic and no ad-hoc DB queries live here (non-negotiable principle
#2, #3). ``evaluate_answer`` is the one tool that may call the LLM -- for
free-text semantic grading only (section 8), with a fuzzy-match fallback.

The vocab MCP *resource* and the standalone Inspector session are LG-08.
"""

from __future__ import annotations

import datetime as dt

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backend.core import read_models, scheduler
from backend.core.read_models import CardStateView, SessionView, UserProfile, WordView
from backend.db.session import session_scope
from backend.mcp_servers.learning_server import quiz
from backend.mcp_servers.learning_server.grading import AnswerEvaluation, grade

INSTRUCTIONS = (
    "German vocabulary learning tools. A deterministic spaced-repetition core "
    "decides what to study; these tools only expose it. Typical flow: "
    "get_user_profile -> create_learning_session (or get_words_due_for_review / "
    "get_weak_words / get_new_words) -> create_quiz -> evaluate_answer -> "
    "update_learning_state after each answer."
)

DEFAULT_DUE_LIMIT = 50
DEFAULT_WEAK_LIMIT = 10
DEFAULT_NEW_COUNT = 10
MAX_LIMIT = 200
NEUTRAL_RESPONSE_MS = 5_000  # used when a caller has no real latency to report


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clamp(value: int) -> int:
    return max(0, min(value, MAX_LIMIT))


def build_server() -> MCPServer:
    server = MCPServer("learning", instructions=INSTRUCTIONS)

    # --- read: profile + word selection --------------------------------------
    @server.tool()
    def get_user_profile(user_id: int) -> UserProfile:
        """Where a learner stands: target, CEFR ceiling, totals, accuracy, due count."""
        with session_scope() as session:
            try:
                return read_models.get_user_profile(session, user_id, as_of=_now())
            except LookupError as exc:
                raise ToolError(str(exc)) from exc

    @server.tool()
    def get_words_due_for_review(user_id: int, limit: int = DEFAULT_DUE_LIMIT) -> list[WordView]:
        """Words whose spaced-repetition interval has elapsed, most overdue first."""
        with session_scope() as session:
            ids = scheduler.words_due_for_review(session, user_id, _now())[: _clamp(limit)]
            return read_models.load_word_views(session, ids)

    @server.tool()
    def get_weak_words(user_id: int, limit: int = DEFAULT_WEAK_LIMIT) -> list[WordView]:
        """The learner's most fragile seen words (lowest SM-2 ease factor first)."""
        with session_scope() as session:
            ids = scheduler.weak_words(session, user_id, _clamp(limit))
            return read_models.load_word_views(session, ids)

    @server.tool()
    def get_new_words(
        user_id: int, topic: str | None = None, count: int = DEFAULT_NEW_COUNT
    ) -> list[WordView]:
        """Unseen words within the learner's CEFR ceiling, most frequent first."""
        with session_scope() as session:
            ids = scheduler.select_new_words(session, user_id, topic, _clamp(count))
            return read_models.load_word_views(session, ids)

    # --- session composition ----------------------------------------------
    @server.tool()
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

    # --- quiz + grading + state -----------------------------------------
    @server.tool()
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
    def evaluate_answer(question_id: str, user_answer: str) -> AnswerEvaluation:
        """Grade an answer. Free-text (de_to_en) uses the LLM for semantic
        grading, falling back to fuzzy matching; others are exact/fuzzy."""
        try:
            spec = quiz.decode_qid(question_id)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        result = grade(spec["t"], spec["r"], user_answer, prompt=spec.get("p", ""))
        return AnswerEvaluation(
            question_id=question_id,
            word_id=spec["w"],
            quiz_type=spec["t"],
            correct=result.correct,
            score=result.score,
            rationale=result.rationale,
            method=result.method,
            expected=spec["r"],
        )

    @server.tool()
    def update_learning_state(
        user_id: int,
        word_id: int,
        correct: bool,
        response_time_ms: int = NEUTRAL_RESPONSE_MS,
    ) -> CardStateView:
        """Record a review outcome and return the word's new spaced-repetition state."""
        with session_scope() as session:
            try:
                scheduler.update_after_review(
                    session, user_id, word_id, correct, response_time_ms, as_of=_now()
                )
            except LookupError as exc:
                raise ToolError(str(exc)) from exc
            return read_models.card_state_view(session, user_id, word_id)

    return server
