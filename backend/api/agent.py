"""The one API surface that drives the *agent*.

Everything else in ``backend/api`` is deterministic and key-free; this endpoint
runs the Anthropic tool-use loop so a browser visitor can type a request in
plain English and watch the agent compose a session through MCP tools.

Because it spends real API tokens it is guarded: it degrades to 503 when no key
is configured, and a crude in-process rate limiter caps calls per client and
per day. The agent still touches data only through MCP tools -- this module just
parses the request and relays the result.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException, Request

from backend.agent.orchestrator import (
    MissingAPIKey,
    SessionRequest,
    run_conversation,
    run_session,
)
from backend.api.schemas import AgentPlanIn, AgentPlanOut

router = APIRouter(prefix="/agent", tags=["agent"])

# --- crude spend guards (in-process; fine for a single-instance demo) ------
_WINDOW_S = 600  # 10 minutes
_PER_CLIENT = 6  # requests / window / client ip
_GLOBAL_PER_DAY = 250  # hard ceiling across everyone
_client_hits: dict[str, list[float]] = {}
_day_bucket: list = ["", 0]  # [yyyy-mm-dd, count]


def _has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _rate_limit(client_ip: str) -> None:
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _day_bucket[0] != today:
        _day_bucket[0], _day_bucket[1] = today, 0
    if _day_bucket[1] >= _GLOBAL_PER_DAY:
        raise HTTPException(429, "the AI coach has hit its daily limit on this demo; try tomorrow")

    hits = [t for t in _client_hits.get(client_ip, []) if now - t < _WINDOW_S]
    if len(hits) >= _PER_CLIENT:
        wait = int(_WINDOW_S - (now - hits[0]))
        raise HTTPException(
            429,
            f"slow down -- up to {_PER_CLIENT} coach requests per 10 minutes; retry in ~{wait}s",
        )
    hits.append(now)
    _client_hits[client_ip] = hits
    _day_bucket[1] += 1


@router.post("/plan", response_model=AgentPlanOut)
def plan(payload: AgentPlanIn, request: Request) -> AgentPlanOut:
    """Run the agent on a natural-language request.

    ``mode="plan"`` composes a study session (server #1 only); ``mode="converse"``
    runs the cross-server loop (server #1 + the notes vault).
    """
    if not _has_key():
        raise HTTPException(503, "the AI coach is not configured on this server (no API key)")
    _rate_limit(request.client.host if request.client else "unknown")

    req = SessionRequest(raw_text=payload.request, user_id=payload.user_id)
    try:
        if payload.mode == "converse":
            conv = run_conversation(req)
            return AgentPlanOut(
                mode="converse",
                stopped=conv.stopped,
                turns=conv.turns,
                reply=conv.reply,
                tool_calls=conv.tool_calls,
                servers_used=conv.servers_used,
            )
        res = run_session(req)
    except MissingAPIKey as exc:  # pragma: no cover - guarded by _has_key above
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface any agent failure as 502
        raise HTTPException(502, f"the agent failed: {exc}") from exc

    return AgentPlanOut(
        mode="plan",
        stopped=res.stopped,
        turns=res.turns,
        reply=res.reply,
        intent=res.intent,
        tool_calls=res.tool_calls,
        session_id=res.session_id,
        review_words=res.review_words,
        new_words=res.new_words,
        quiz=res.quiz,
    )
