"""Weekly mistake-pattern insights -- an agent job spanning both MCP servers.

The agent reads the learner's recent misses and diagnostic labels from the
LEARNING server (``get_mistake_summary`` / ``get_weak_words``), finds concrete
patterns, and records a dated summary in the NOTES vault via the SECONDARY
server (``log_progress``). One natural-language reasoning step, two independent
tool surfaces -- the orchestration this project exists to demonstrate. It never touches scheduling.

    python -m backend.agent --insights --user-id 1
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from backend.agent.orchestrator import _anthropic_client, _run_loop
from backend.tracing.tracer import Tracer, get_tracer

DEFAULT_MODEL = "claude-opus-5"
INSIGHTS_MAX_TURNS = 8

INSIGHTS_SYSTEM = """\
You are a German-learning coach reviewing user_id={user_id}'s recent mistakes.

Tools come from two servers:
- LEARNING: get_mistake_summary (recent wrong answers + diagnostic labels like
  wrong_gender / spelling / false_friend, and counts by label), get_weak_words.
- NOTES: log_progress (appends a dated section to the learner's progress.md).

Your job is NOT done until you have called log_progress. The analysis must be
written to the note, not just stated in your reply. Never end your turn with the
findings only in text.

Do this, in order:
1. Call get_mistake_summary and get_weak_words.
2. Work out 1-3 concrete patterns. Every claim must cite specific words from the
   data (e.g. "gender errors on -ung nouns: Meinung, Rechnung"). If the data
   does not support a pattern, note that there is not enough signal yet.
3. Call log_progress -- heading "Weekly insights", summary = a short Markdown
   body: a one-line headline, then one bullet per pattern (pattern -- evidence
   -- one short tip), then a final "Focus next: <skill or topic>" line. This
   call is mandatory; the task is incomplete without it.
4. Only AFTER log_progress returns, reply to the learner in one sentence: the
   headline and the focus.

If there are no misses at all, still call log_progress with a brief "nothing to
flag yet, keep it up" note, then say so.
"""


@dataclass
class InsightsResult:
    stopped: str  # "completed" | "max_turns" | "refusal"
    turns: int
    reply: str
    note_written: bool
    tool_calls: list[str] = field(default_factory=list)
    servers_used: list[str] = field(default_factory=list)


_NOTE_TOOLS = {"log_progress", "write_note", "append_note"}


def run_insights(
    user_id: int,
    *,
    mcp_client=None,
    llm_client=None,
    tracer: Tracer | None = None,
    model: str | None = None,
) -> InsightsResult:
    from backend.agent.mcp_client import build_default_clients

    tracer = tracer or get_tracer()
    mcp = mcp_client or build_default_clients(tracer=tracer)
    llm = llm_client or _anthropic_client()
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    used: set[str] = set()

    def on_tool(name: str, _args: dict, _payload: Any) -> None:
        server = getattr(mcp, "server_for", lambda _n: None)(name)
        if server:
            used.add(server)

    outcome = _run_loop(
        system=INSIGHTS_SYSTEM.format(user_id=user_id),
        user_text=f"Review my recent German mistakes (user_id={user_id}) and log what you find.",
        mcp=mcp,
        llm=llm,
        model=model,
        tracer=tracer,
        max_turns=INSIGHTS_MAX_TURNS,
        on_tool=on_tool,
    )
    return InsightsResult(
        stopped=outcome.stopped,
        turns=outcome.turns,
        reply=outcome.reply,
        note_written=any(name in _NOTE_TOOLS for name in outcome.tool_calls),
        tool_calls=outcome.tool_calls,
        servers_used=sorted(used),
    )
