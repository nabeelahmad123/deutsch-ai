"""Agent tool-calling loop against the Anthropic API (CLAUDE.md section 9).

The agent does ONE piece of natural-language reasoning -- turning a request like
"I have 10 minutes, German for work" into a time budget + topic -- and then calls
MCP server #1 tools to compose the session. It never picks words or computes
intervals itself (non-negotiable principle #2).

Every LLM turn is traced as an ``agent_decision`` and every tool call is traced
by ``MCPToolClient`` (principle #4).

LG-09 covers intent + the loop through ``create_learning_session``. Quiz
generation and answer grading (steps 4-5 of section 9) land in LG-10.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.agent.mcp_client import MCPToolClient, MCPToolError
from backend.tracing.tracer import TraceEvent, Tracer, get_tracer

DEFAULT_MODEL = "claude-opus-5"
MAX_TURNS = 8
MAX_TOKENS = 4096

SYSTEM = """\
You plan a single German vocabulary study session for learner user_id={user_id}.

1. Read the learner's request and work out two things: how many minutes they have
   (an integer) and the topic/target, if any (one of: work, travel, general,
   exam, or a subject like "food"; use null if unclear). This is the only
   judgement you make.
2. You MAY call get_user_profile / get_words_due_for_review / get_weak_words /
   get_new_words to understand where the learner stands.
3. Call create_learning_session exactly once, passing the minutes and topic you
   inferred. The deterministic scheduler decides which words -- never choose,
   reorder, or invent vocabulary yourself, and never compute review dates.

When create_learning_session has returned, briefly tell the learner what the
session contains and stop. Do not call quiz or grading tools yet.
"""


@dataclass
class SessionRequest:
    raw_text: str
    user_id: int


@dataclass
class SessionResult:
    stopped: str  # "completed" | "no_session" | "max_turns" | "refusal"
    intent: dict = field(default_factory=dict)  # {minutes_available, topic}
    session_id: int | None = None
    review_words: list[dict] = field(default_factory=list)
    new_words: list[dict] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    turns: int = 0
    reply: str = ""


def _anthropic_client():
    from anthropic import Anthropic

    return Anthropic()  # resolves ANTHROPIC_API_KEY / auth profile


def _blocks_to_dicts(content: Any) -> list[dict]:
    out: list[dict] = []
    for block in content:
        kind = getattr(block, "type", None)
        if kind == "text":
            out.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            out.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
    return out


def run_session(
    request: SessionRequest,
    *,
    mcp_client: MCPToolClient | None = None,
    llm_client=None,
    tracer: Tracer | None = None,
    model: str | None = None,
) -> SessionResult:
    """Run the intent->tools loop and return the composed session."""
    tracer = tracer or get_tracer()
    mcp = mcp_client or MCPToolClient(tracer=tracer)
    llm = llm_client or _anthropic_client()
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    tools = mcp.tool_specs()
    system = SYSTEM.format(user_id=request.user_id)
    messages: list[dict] = [{"role": "user", "content": request.raw_text}]

    result = SessionResult(stopped="max_turns")
    session_payload: dict | None = None

    for turn in range(1, MAX_TURNS + 1):
        result.turns = turn
        response = llm.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
        )
        blocks = list(response.content)
        text = " ".join(b.text for b in blocks if getattr(b, "type", None) == "text").strip()
        tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]

        tracer.emit(
            TraceEvent(
                kind="agent_decision",
                name="agent.turn",
                trace_id=uuid.uuid4().hex,
                input={"turn": turn, "request": request.raw_text},
                output={
                    "stop_reason": response.stop_reason,
                    "text": text[:400],
                    "tools_requested": [b.name for b in tool_uses],
                },
                success=True,
            )
        )
        messages.append({"role": "assistant", "content": _blocks_to_dicts(blocks)})
        result.reply = text or result.reply

        if response.stop_reason == "refusal":
            result.stopped = "refusal"
            break
        if not tool_uses:
            result.stopped = "completed" if session_payload else "no_session"
            break

        tool_results: list[dict] = []
        for block in tool_uses:
            result.tool_calls.append(block.name)
            try:
                payload = mcp.call(block.name, block.input or {})
                if block.name == "create_learning_session":
                    session_payload = payload if isinstance(payload, dict) else None
                    result.intent = {
                        "minutes_available": (block.input or {}).get("minutes_available"),
                        "topic": (block.input or {}).get("topic"),
                    }
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(payload, default=str),
                    }
                )
            except MCPToolError as exc:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": exc.message,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    if session_payload is not None:
        result.session_id = session_payload.get("session_id")
        result.review_words = session_payload.get("review_words", [])
        result.new_words = session_payload.get("new_words", [])

    return result
