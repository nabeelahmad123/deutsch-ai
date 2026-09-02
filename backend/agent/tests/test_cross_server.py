"""LG-12: one conversation spanning both MCP servers, with a scripted LLM.

The DoD (section 17): the trace must show tools from both servers and the
reasoning between them.
"""

import json

from backend.agent.mcp_client import (
    MCPToolClient,
    MultiServerToolClient,
    build_default_clients,
)
from backend.agent.orchestrator import SessionRequest, run_conversation
from backend.agent.scripted_llm import FakeLLM, response, text_block, tool_use
from backend.mcp_servers.learning_server.server import build_server as build_learning
from backend.mcp_servers.secondary_server.server import build_server as build_notes
from backend.tracing.tracer import Tracer


def test_multi_client_unions_specs_and_routes(seeded_db, tmp_path):
    tracer = Tracer(tmp_path / "t.jsonl")
    mcp = MultiServerToolClient(
        [
            MCPToolClient(build_learning(tracer=tracer), tracer=tracer),
            MCPToolClient(build_notes(tracer=tracer), tracer=tracer),
        ]
    )
    names = {s["name"] for s in mcp.tool_specs()}
    assert "create_learning_session" in names and "log_progress" in names
    assert mcp.server_for("create_learning_session") == "learning"
    assert mcp.server_for("log_progress") == "notes"
    assert mcp.server_for("nope") is None

    profile = mcp.call("get_user_profile", {"user_id": 1})
    assert profile["user_id"] == 1
    entry = mcp.call("log_progress", {"summary": "hello", "date": "2026-09-03"})
    assert entry["note"] == "progress.md"


def _run(script, tmp_path, text):
    tracer = Tracer(tmp_path / "trace.jsonl")
    result = run_conversation(
        SessionRequest(raw_text=text, user_id=1),
        mcp_client=build_default_clients(tracer=tracer),
        llm_client=FakeLLM(script),
        tracer=tracer,
    )
    events = [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text().splitlines()]
    return result, events


def test_one_conversation_uses_both_servers(seeded_db, tmp_path, vault_path):
    script = [
        response(
            text_block("First, where does the learner stand?"),
            tool_use("get_user_profile", {"user_id": 1}),
        ),
        response(
            text_block("Compose a 10-minute work session."),
            tool_use(
                "create_learning_session",
                {"user_id": 1, "minutes_available": 10, "topic": "work"},
            ),
        ),
        response(
            text_block("Now record the plan in the learner's notes."),
            tool_use(
                "log_progress",
                {
                    "summary": "Planned a 10-min work session.",
                    "heading": "Plan",
                    "date": "2026-09-03",
                },
            ),
        ),
        response(
            text_block("Done: session composed and logged to progress.md."), stop_reason="end_turn"
        ),
    ]
    result, events = _run(
        script, tmp_path, "Set me up a 10-minute German work session and note where I'm at"
    )

    assert result.stopped == "completed"
    assert result.servers_used == ["learning", "notes"]
    assert result.tool_calls == ["get_user_profile", "create_learning_session", "log_progress"]

    # the trace interleaves agent reasoning with calls to BOTH servers
    names = [e["name"] for e in events]
    assert names.count("agent.turn") == 4
    assert "learning.tool.create_learning_session" in names
    assert "notes.tool.log_progress" in names
    li = names.index("agent.tool_call.create_learning_session")
    ni = names.index("agent.tool_call.log_progress")
    assert li < ni  # learning first, then notes -- with an agent.turn between
    assert any(e["name"] == "agent.turn" for e in events[li + 1 : ni])

    # the note was actually written
    assert (vault_path / "progress.md").read_text().count("## 2026-09-03") == 1


def test_error_in_one_server_does_not_break_the_conversation(seeded_db, tmp_path, vault_path):
    script = [
        response(tool_use("get_user_profile", {"user_id": 999})),  # unknown user -> error
        response(tool_use("read_note", {"name": "../../etc/hosts"})),  # traversal -> error
        response(tool_use("log_progress", {"summary": "recovered", "date": "2026-09-03"})),
        response(text_block("Handled it."), stop_reason="end_turn"),
    ]
    result, events = _run(script, tmp_path, "log something")
    assert result.stopped == "completed"
    errors = [e for e in events if e["kind"] == "error"]
    assert {e["name"] for e in errors} >= {
        "agent.tool_call.get_user_profile",
        "agent.tool_call.read_note",
    }
    assert "notes" in result.servers_used  # the final log_progress still ran


def test_refusal_in_conversation(seeded_db, tmp_path):
    script = [response(text_block("No."), stop_reason="refusal")]
    result, _ = _run(script, tmp_path, "do something disallowed")
    assert result.stopped == "refusal"
