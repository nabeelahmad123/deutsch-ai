"""Weekly mistake-pattern insights: one agent job across both MCP servers."""

import datetime as dt
import json

from backend.agent.insights import run_insights
from backend.agent.mcp_client import build_default_clients
from backend.agent.scripted_llm import FakeLLM, response, text_block, tool_use
from backend.db.models import ReviewLog
from backend.db.session import session_scope
from backend.tracing.tracer import Tracer

from .conftest import T0


def _add_misses(rows):
    with session_scope() as s:
        for i, (wid, etype) in enumerate(rows):
            s.add(
                ReviewLog(
                    user_id=1,
                    word_id=wid,
                    timestamp=T0 + dt.timedelta(days=i + 1),
                    correct=False,
                    response_time_ms=8000,
                    source="review",
                    error_type=etype,
                )
            )


def _run(script, tmp_path):
    tracer = Tracer(tmp_path / "trace.jsonl")
    res = run_insights(
        1,
        mcp_client=build_default_clients(tracer=tracer),
        llm_client=FakeLLM(script),
        tracer=tracer,
    )
    events = [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text().splitlines()]
    return res, events


def test_get_mistake_summary_tool_aggregates_and_samples(seeded_db, tmp_path):
    _add_misses([(1, "wrong_gender"), (3, "wrong_gender"), (5, "spelling")])
    mcp = build_default_clients(tracer=Tracer(tmp_path / "t.jsonl"))
    r = mcp.call("get_mistake_summary", {"user_id": 1})
    assert r["by_error_type"]["wrong_gender"] == 2
    assert r["total_misses"] >= 3  # + the fixture's own unlabelled miss
    assert r["recent_misses"] and "lemma" in r["recent_misses"][0]


def test_insights_spans_both_servers_and_writes_a_note(seeded_db, tmp_path, vault_path):
    _add_misses([(1, "wrong_gender"), (3, "wrong_gender"), (5, "spelling"), (7, "false_friend")])
    script = [
        response(
            text_block("Let me see the mistakes."),
            tool_use("get_mistake_summary", {"user_id": 1}),
        ),
        response(
            text_block("And which words are fragile."),
            tool_use("get_weak_words", {"user_id": 1, "limit": 10}),
        ),
        response(
            text_block("Logging the patterns."),
            tool_use(
                "log_progress",
                {
                    "summary": "Gender errors on wort1, wort3.\nFocus next: noun gender",
                    "heading": "Weekly insights",
                    "date": "2026-02-01",
                },
            ),
        ),
        response(
            text_block("Gender errors dominate — focus on noun gender."), stop_reason="end_turn"
        ),
    ]
    res, events = _run(script, tmp_path)

    assert res.stopped == "completed"
    assert res.servers_used == ["learning", "notes"]
    assert res.note_written is True
    assert res.tool_calls == ["get_mistake_summary", "get_weak_words", "log_progress"]

    names = [e["name"] for e in events]
    assert "learning.tool.get_mistake_summary" in names
    assert "notes.tool.log_progress" in names
    li = names.index("agent.tool_call.get_mistake_summary")
    ni = names.index("agent.tool_call.log_progress")
    assert li < ni and any(e["name"] == "agent.turn" for e in events[li + 1 : ni])
    assert (vault_path / "progress.md").read_text().count("Weekly insights") >= 1


def test_insights_refusal_is_reported(seeded_db, tmp_path):
    res, _ = _run([response(text_block("No."), stop_reason="refusal")], tmp_path)
    assert res.stopped == "refusal" and res.note_written is False
