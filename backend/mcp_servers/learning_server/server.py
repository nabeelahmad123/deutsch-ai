"""MCP server #1 -- learning tools (CLAUDE.md section 8).

Every tool is a thin wrapper: open a DB session, delegate to ``backend.core``
(scheduler for decisions, read_models for hydration), return a typed dataclass.
No scheduling logic and no ad-hoc DB queries live here (non-negotiable principle
#2, #3).

LG-06 ships the four read tools + ``get_user_profile``. create_quiz /
evaluate_answer / update_learning_state / create_learning_session and the vocab
resource land in LG-07 / LG-08.
"""

from __future__ import annotations

import datetime as dt

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backend.core import read_models, scheduler
from backend.core.read_models import UserProfile, WordView
from backend.db.session import session_scope

INSTRUCTIONS = (
    "German vocabulary learning tools. A deterministic spaced-repetition core "
    "decides what to study; these tools only expose it. Call get_user_profile "
    "first to see where a learner stands, then get_words_due_for_review / "
    "get_weak_words / get_new_words to assemble study material."
)

DEFAULT_DUE_LIMIT = 50
DEFAULT_WEAK_LIMIT = 10
DEFAULT_NEW_COUNT = 10
MAX_LIMIT = 200


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clamp(value: int) -> int:
    return max(0, min(value, MAX_LIMIT))


def build_server() -> MCPServer:
    server = MCPServer("learning", instructions=INSTRUCTIONS)

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

    return server
