"""MCP server #1 -- tool discovery + invocation (LG-06).

Calls run in-process via ``server.call_tool``; the standalone MCP-client /
Inspector session is LG-08.
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from backend.mcp_servers.learning_server.server import MAX_LIMIT, build_server


def _call(name: str, args: dict):
    return asyncio.run(build_server().call_tool(name, args))


def test_tool_manifest():
    tools = asyncio.run(build_server().list_tools())
    names = {t.name for t in tools}
    assert names == {
        "get_user_profile",
        "get_words_due_for_review",
        "get_weak_words",
        "get_new_words",
    }
    for t in tools:
        assert t.description
        assert t.input_schema["properties"]["user_id"]["type"] == "integer"
        assert t.output_schema is not None


def test_get_user_profile_shape(seeded_db):
    res = _call("get_user_profile", {"user_id": 1})
    assert res.is_error is False
    p = res.structured_content
    assert p["user_id"] == 1
    assert p["target"] == "work"
    assert p["total_reviews"] == 3
    assert p["words_seen"] == 2
    assert p["cefr_ceiling"] == "A2"  # word 2 (A1) answered correctly
    assert p["overall_accuracy"] == pytest.approx(1 / 3, abs=1e-4)


def test_get_user_profile_unknown_user_is_tool_error(seeded_db):
    with pytest.raises(ToolError):
        _call("get_user_profile", {"user_id": 404})


def test_get_weak_words(seeded_db):
    rows = _call("get_weak_words", {"user_id": 1, "limit": 5}).structured_content["result"]
    assert [r["id"] for r in rows][:1] == [1]  # two failures -> weakest
    assert all("translation_en" in r for r in rows)


def test_get_new_words_excludes_seen_and_filters_topic(seeded_db):
    rows = _call("get_new_words", {"user_id": 1, "topic": "food", "count": 10})
    ids = [r["id"] for r in rows.structured_content["result"]]
    assert ids == [3, 7, 12]  # food words, word 3 unseen (only 1 & 2 seen)


def test_get_words_due_for_review(seeded_db):
    rows = _call("get_words_due_for_review", {"user_id": 1}).structured_content["result"]
    # both seen words are long overdue (fixture timestamps are in the past);
    # word 2 (due T0+1d) sorts before word 1 (due T0+2d, after its 2nd failure).
    assert [r["id"] for r in rows] == [2, 1]


def test_limit_is_clamped(seeded_db):
    # count above MAX_LIMIT must not raise
    res = _call("get_new_words", {"user_id": 1, "count": MAX_LIMIT + 10_000})
    assert res.is_error is False
