"""Standalone MCP-client session against server #1 -- the LG-08 DoD check.

A real ``ClientSession`` talks to the server over an in-memory transport (full
JSON-RPC: initialize, list_tools, list_resources, read_resource, call_tool),
independent of any agent code. This is the automated stand-in for a manual MCP
Inspector / Claude Desktop session.
"""

import asyncio
import json

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams

from backend.mcp_servers.learning_server.server import build_server


async def _run_session(scenario):
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        server = build_server()._lowlevel_server
        async with anyio.create_task_group() as tg:

            async def _serve():
                await server.run(
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                    raise_exceptions=True,
                )

            tg.start_soon(_serve)
            async with ClientSession(client_streams[0], client_streams[1]) as client:
                await client.initialize()
                await scenario(client)
            tg.cancel_scope.cancel()


def _drive(scenario):
    asyncio.run(_run_session(scenario))


def test_full_manual_session(seeded_db):
    async def scenario(client: ClientSession):
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {
            "get_user_profile",
            "create_learning_session",
            "create_quiz",
            "evaluate_answer",
            "update_learning_state",
        } <= tools

        resources = {str(r.uri) for r in (await client.list_resources()).resources}
        assert "vocab://words" in resources
        templates = {
            t.uri_template for t in (await client.list_resource_templates()).resource_templates
        }
        assert "vocab://words/{cefr_level}" in templates
        assert "vocab://word/{lemma}" in templates

        # resource read
        overview = json.loads((await client.read_resource("vocab://words")).contents[0].text)
        assert overview["total"] == 30
        a1 = json.loads((await client.read_resource("vocab://words/A1")).contents[0].text)
        assert len(a1) == 10 and all(w["cefr_level"] == "A1" for w in a1)
        one = json.loads((await client.read_resource("vocab://word/wort5")).contents[0].text)
        assert one["lemma"] == "wort5"

        # a real study flow over the wire
        args = {"user_id": 1, "minutes_available": 10}
        session = (await client.call_tool("create_learning_session", args)).structured_content
        assert session["session_id"] == 1

        made = await client.call_tool("create_quiz", {"word_ids": [3, 5], "quiz_type": "en_to_de"})
        qid = made.structured_content["result"][0]["question_id"]

        graded = await client.call_tool(
            "evaluate_answer", {"question_id": qid, "user_answer": "wort3"}
        )
        assert graded.structured_content["correct"] is True

        state = await client.call_tool(
            "update_learning_state", {"user_id": 1, "word_id": 3, "correct": True}
        )
        assert state.structured_content["repetitions"] == 1

    _drive(scenario)


def test_protocol_errors_are_reported_not_crashes(seeded_db):
    async def scenario(client: ClientSession):
        # unknown user -> is_error result (not a crash)
        bad = await client.call_tool("get_user_profile", {"user_id": 999})
        assert bad.is_error is True

        # a missing resource -> a JSON-RPC error the client raises
        with pytest.raises(MCPError):
            await client.read_resource("vocab://word/does-not-exist")
        with pytest.raises(MCPError):
            await client.read_resource("vocab://words/C1")

        # the session is still usable after both failures
        ok = await client.call_tool("get_user_profile", {"user_id": 1})
        assert ok.is_error is False

    _drive(scenario)
