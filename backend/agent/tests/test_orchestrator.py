"""Orchestrator loop against a scripted LLM -- deterministic, no network.

A real-API smoke test lives in test_orchestrator_live.py (skipped without a key).
"""

import json

from backend.agent.mcp_client import MCPToolClient
from backend.agent.orchestrator import MAX_TURNS, SessionRequest, run_session
from backend.tracing.tracer import Tracer

from .fake_llm import FakeLLM, response, text_block, tool_use


def _run(script, tmp_path, user_id=1, text="I have 10 minutes, German for work"):
    tracer = Tracer(tmp_path / "trace.jsonl")
    result = run_session(
        SessionRequest(raw_text=text, user_id=user_id),
        mcp_client=MCPToolClient(tracer=tracer),
        llm_client=FakeLLM(script),
        tracer=tracer,
    )
    events = [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text().splitlines()]
    return result, events


def test_composes_session_from_natural_language(seeded_db, tmp_path):
    script = [
        response(
            text_block("The learner has 10 minutes, topic work. Let me check where they stand."),
            tool_use("get_user_profile", {"user_id": 1}),
        ),
        response(
            text_block("Composing the session."),
            tool_use(
                "create_learning_session", {"user_id": 1, "minutes_available": 10, "topic": "work"}
            ),
        ),
        response(text_block("Here is your 10-minute work session."), stop_reason="end_turn"),
    ]
    result, events = _run(script, tmp_path)

    assert result.stopped == "completed"
    assert result.turns == 3
    assert result.tool_calls == ["get_user_profile", "create_learning_session"]
    assert result.intent == {"minutes_available": 10, "topic": "work"}
    assert result.session_id == 1
    assert isinstance(result.review_words, list) and isinstance(result.new_words, list)
    assert result.reply == "Here is your 10-minute work session."

    # trace: an agent_decision per turn, plus the tool calls in order
    decisions = [e for e in events if e["kind"] == "agent_decision"]
    assert len(decisions) == 3
    assert decisions[0]["output"]["tools_requested"] == ["get_user_profile"]
    agent_calls = [e["name"] for e in events if e["name"].startswith("agent.tool_call.")]
    assert agent_calls == [
        "agent.tool_call.get_user_profile",
        "agent.tool_call.create_learning_session",
    ]


def test_tool_error_is_fed_back_not_raised(seeded_db, tmp_path):
    script = [
        response(tool_use("get_user_profile", {"user_id": 999})),  # unknown user -> error
        response(
            tool_use(
                "create_learning_session", {"user_id": 1, "minutes_available": 5, "topic": None}
            )
        ),
        response(text_block("Recovered."), stop_reason="end_turn"),
    ]
    result, events = _run(script, tmp_path)

    assert result.stopped == "completed"
    assert result.session_id is not None
    err_events = [e for e in events if e["kind"] == "error"]
    assert any(e["name"] == "agent.tool_call.get_user_profile" for e in err_events)


def test_stops_at_max_turns_when_agent_never_finishes(seeded_db, tmp_path):
    loop_forever = [
        response(tool_use("get_new_words", {"user_id": 1, "count": 1}, tool_id=f"t{i}"))
        for i in range(MAX_TURNS + 2)
    ]
    result, _ = _run(loop_forever, tmp_path)
    assert result.stopped == "max_turns"
    assert result.turns == MAX_TURNS


def test_no_session_when_agent_answers_without_composing(seeded_db, tmp_path):
    script = [response(text_block("You should study for a while."), stop_reason="end_turn")]
    result, _ = _run(script, tmp_path)
    assert result.stopped == "no_session"
    assert result.session_id is None


def test_refusal_is_handled(seeded_db, tmp_path):
    script = [response(text_block("I can't help with that."), stop_reason="refusal")]
    result, _ = _run(script, tmp_path)
    assert result.stopped == "refusal"
    assert result.turns == 1


def test_llm_receives_tool_specs_and_system_prompt(seeded_db, tmp_path):
    fake = FakeLLM([response(text_block("done"), stop_reason="end_turn")])
    run_session(
        SessionRequest(raw_text="quick german pls", user_id=7),
        mcp_client=MCPToolClient(tracer=Tracer(tmp_path / "t.jsonl")),
        llm_client=fake,
        tracer=Tracer(tmp_path / "t.jsonl"),
    )
    call = fake.calls[0]
    assert "user_id=7" in call["system"]
    assert {t["name"] for t in call["tools"]} >= {"create_learning_session", "get_new_words"}
