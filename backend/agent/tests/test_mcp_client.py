"""MCPToolClient: Anthropic-shaped specs + traced, unwrapped sync calls."""

import json

import pytest

from backend.agent.mcp_client import MCPToolClient, MCPToolError
from backend.tracing.tracer import Tracer


def test_tool_specs_are_anthropic_shaped(seeded_db):
    specs = {s["name"]: s for s in MCPToolClient().tool_specs()}
    assert "create_learning_session" in specs
    for spec in specs.values():
        assert set(spec) == {"name", "description", "input_schema"}
        assert spec["input_schema"]["type"] == "object"


def test_call_unwraps_structured_content(seeded_db):
    client = MCPToolClient()
    profile = client.call("get_user_profile", {"user_id": 1})
    assert isinstance(profile, dict) and profile["user_id"] == 1  # not {"result": ...}

    new_words = client.call("get_new_words", {"user_id": 1, "count": 3})
    assert isinstance(new_words, list) and len(new_words) == 3


def test_call_raises_typed_error_on_tool_error(seeded_db):
    with pytest.raises(MCPToolError) as excinfo:
        MCPToolClient().call("get_user_profile", {"user_id": 999})
    assert excinfo.value.tool == "get_user_profile"


def test_calls_are_traced(seeded_db, tmp_path):
    tracer = Tracer(tmp_path / "t.jsonl")
    client = MCPToolClient(tracer=tracer)
    client.call("get_user_profile", {"user_id": 1})

    events = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    names = [e["name"] for e in events]
    assert "agent.tool_call.get_user_profile" in names  # agent-side
    assert "learning.tool.get_user_profile" in names  # server-side (shared tracer)
