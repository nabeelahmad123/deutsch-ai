"""MCP server #2 (notes) -- tool discovery, invocation, tracing, independence."""

import ast
import asyncio
import json
import pathlib

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from backend.mcp_servers.secondary_server.server import build_server
from backend.tracing.tracer import Tracer


def _call(name, args):
    return asyncio.run(build_server().call_tool(name, args))


def _text(result):
    sc = result.structured_content
    return sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc


def test_tool_manifest():
    tools = asyncio.run(build_server().list_tools())
    assert {t.name for t in tools} == {
        "list_notes",
        "read_note",
        "write_note",
        "append_note",
        "log_progress",
    }
    for t in tools:
        assert t.description and t.output_schema is not None


def test_write_append_read_list(vault_path):
    _call("write_note", {"name": "notes/plan", "content": "# Plan"})
    _call("append_note", {"name": "notes/plan", "content": "- item"})
    assert _text(_call("read_note", {"name": "notes/plan"})) == "# Plan\n\n- item\n"
    listed = _call("list_notes", {}).structured_content["result"]
    assert [n["name"] for n in listed] == ["notes/plan.md"]


def test_log_progress_tool_writes_progress_md(vault_path):
    out = _call(
        "log_progress", {"summary": "did the thing", "heading": "Recap", "date": "2026-09-03"}
    ).structured_content
    assert out["note"] == "progress.md"
    assert "## 2026-09-03 — Recap" in _text(_call("read_note", {"name": "progress"}))


def test_unsafe_name_is_tool_error(vault_path):
    with pytest.raises(ToolError):
        _call("read_note", {"name": "../../secrets"})


def test_calls_are_traced(vault_path, tmp_path):
    tracer = Tracer(tmp_path / "t.jsonl")
    server = build_server(tracer=tracer)
    asyncio.run(server.call_tool("write_note", {"name": "a", "content": "b"}))
    names = [json.loads(x)["name"] for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert names == ["notes.tool.write_note"]


def test_secondary_server_is_independent_of_server_one_and_core():
    """Principle #5: server #2 shares no domain code with server #1 / backend.core."""
    pkg = pathlib.Path(__file__).resolve().parents[1] / "secondary_server"
    banned = ("backend.core", "backend.mcp_servers.learning_server", "backend.db")
    offenders = {}
    for path in pkg.rglob("*.py"):
        tree = ast.parse(path.read_text())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
            elif isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
        bad = [m for m in mods if any(m == b or m.startswith(b + ".") for b in banned)]
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, offenders
