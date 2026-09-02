"""Agent tool-calling loop against the Anthropic API (CLAUDE.md section 9).

The agent parses intent (the ONE place natural-language reasoning belongs) and
then calls MCP tools -- it never computes scheduling decisions itself
(non-negotiable principle #2). Every tool call is traced via
``backend/tracing/tracer.py``.

Day-1 status: stub. This is build-order step 4.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionRequest:
    raw_text: str
    user_id: int


def run_session(request: SessionRequest) -> dict:
    """Turn a natural-language request into a composed, graded learning session.

    Steps (section 9): parse intent -> get due/weak/new words via MCP server #1
    -> create_learning_session -> generate quiz -> grade + update_learning_state.
    """
    raise NotImplementedError("orchestrator lands in build-order step 4")
