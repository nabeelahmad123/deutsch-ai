"""Each fault kind is reproducibly triggerable."""

import json
import time

import pytest

from backend.agent.failure_injection import (
    AMBIGUOUS_REQUESTS,
    MALFORMED_PAYLOAD,
    FaultInjectingClient,
    FaultKind,
    FaultSpec,
    ambiguate,
    wrap_tool,
)
from backend.agent.mcp_client import MCPToolError
from backend.tracing.tracer import Tracer


class _StubClient:
    """A trivial inner client that always succeeds."""

    def __init__(self):
        self.calls = []

    def tool_specs(self):
        return [{"name": "get_new_words", "description": "", "input_schema": {"type": "object"}}]

    def server_for(self, name):
        return "learning"

    def call(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"ok": True, "name": name}


def test_timeout_fault_raises_promptly_and_is_recorded(tmp_path):
    tracer = Tracer(tmp_path / "t.jsonl")
    client = FaultInjectingClient(
        _StubClient(),
        [FaultSpec(FaultKind.timeout, delay_seconds=5.0)],
        tracer=tracer,
    )
    start = time.perf_counter()
    with pytest.raises(MCPToolError, match="timed out"):
        client.call("get_new_words", {"user_id": 1})
    assert time.perf_counter() - start < 1.0  # capped -- never actually hangs

    assert client.injected == [{"tool": "get_new_words", "kind": "timeout", "fire": 1}]
    events = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert events[0]["kind"] == "fault_injected"
    assert events[0]["name"] == "fault.timeout.get_new_words"


def test_malformed_response_fault_returns_junk_not_the_real_payload():
    inner = _StubClient()
    client = FaultInjectingClient(inner, [FaultSpec(FaultKind.malformed_response)])
    out = client.call("get_new_words")
    assert out == MALFORMED_PAYLOAD
    assert out.get("__malformed__") is True
    assert inner.calls == []  # inner was never reached


def test_probability_zero_never_injects():
    inner = _StubClient()
    client = FaultInjectingClient(inner, [FaultSpec(FaultKind.timeout, probability=0.0)])
    for _ in range(20):
        assert client.call("get_new_words")["ok"] is True
    assert client.injected == []


def test_target_tool_scopes_the_fault():
    client = FaultInjectingClient(
        _StubClient(),
        [FaultSpec(FaultKind.malformed_response, target_tool="get_new_words")],
    )
    assert client.call("get_new_words").get("__malformed__") is True
    assert client.call("get_user_profile") == {"ok": True, "name": "get_user_profile"}


def test_max_fires_limits_injection():
    client = FaultInjectingClient(
        _StubClient(),
        [FaultSpec(FaultKind.timeout, max_fires=1)],
        seed=1,
    )
    with pytest.raises(MCPToolError):
        client.call("x")
    assert client.call("x")["ok"] is True  # second call passes through
    assert len(client.injected) == 1


def test_injection_is_deterministic_for_a_seed():
    def run():
        c = FaultInjectingClient(
            _StubClient(), [FaultSpec(FaultKind.timeout, probability=0.5)], seed=42
        )
        outcomes = []
        for i in range(30):
            try:
                c.call(f"t{i}")
                outcomes.append("ok")
            except MCPToolError:
                outcomes.append("fault")
        return outcomes

    assert run() == run()


def test_wrap_tool_primitive():
    hits = []
    wrapped = wrap_tool(
        lambda name, args=None: {"real": name},
        [FaultSpec(FaultKind.malformed_response)],
        on_inject=lambda tool, spec: hits.append(tool),
    )
    assert wrapped("foo").get("__malformed__") is True
    assert hits == ["foo"]


@pytest.mark.parametrize(
    ("text", "must_not_contain"),
    [
        ("I have 10 minutes, German for work", "10 minutes"),
        ("about 20 mins of German for travel", "for travel"),
        ("give me a 1 hour session for my trip", "for my trip"),
    ],
)
def test_ambiguate_strips_time_and_topic(text, must_not_contain):
    out = ambiguate(text)
    assert must_not_contain.lower() not in out.lower()
    assert out  # never empty


def test_ambiguate_falls_back_when_everything_stripped():
    assert ambiguate("30 minutes") == "some time"  # not empty
    assert ambiguate("") == "let's do some German"


def test_ambiguous_request_bank_is_vague():
    for req in AMBIGUOUS_REQUESTS:
        assert not any(ch.isdigit() for ch in req)


def test_fault_injecting_client_plugs_into_the_orchestrator(seeded_db, tmp_path):
    """A one-shot timeout on create_learning_session: the loop feeds is_error
    back, the (scripted) model retries, and the session still composes."""
    from backend.agent.mcp_client import build_default_clients
    from backend.agent.orchestrator import SessionRequest, run_session
    from backend.agent.scripted_llm import FakeLLM, response, text_block, tool_use

    tracer = Tracer(tmp_path / "trace.jsonl")
    inner = build_default_clients(tracer=tracer)
    sabotaged = FaultInjectingClient(
        inner,
        [FaultSpec(FaultKind.timeout, target_tool="create_learning_session", max_fires=1)],
        tracer=tracer,
    )
    args = {"user_id": 1, "minutes_available": 10, "topic": None}
    script = [
        response(tool_use("create_learning_session", args)),  # sabotaged
        response(tool_use("create_learning_session", args)),  # retry -> ok
        response(text_block("Composed on the retry."), stop_reason="end_turn"),
    ]
    result = run_session(
        SessionRequest("10 min german", 1),
        mcp_client=sabotaged,
        llm_client=FakeLLM(script),
        tracer=tracer,
    )

    assert result.session_id is not None  # recovered
    assert result.tool_calls == ["create_learning_session", "create_learning_session"]
    assert len(sabotaged.injected) == 1
    kinds = [json.loads(x)["kind"] for x in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert "fault_injected" in kinds  # the sabotage is on the record
