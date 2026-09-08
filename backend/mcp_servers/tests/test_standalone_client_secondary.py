"""Standalone MCP-client session against server #2.

A real ``ClientSession`` over an in-memory transport, independent of the agent
and of server #1. Automated stand-in for a manual MCP Inspector session.
"""

import asyncio

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from backend.mcp_servers.secondary_server.server import build_server


async def _run(scenario):
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


def test_notes_session(vault_path):
    async def scenario(client: ClientSession):
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"list_notes", "read_note", "write_note", "append_note", "log_progress"}

        await client.call_tool("write_note", {"name": "journal", "content": "day 1"})
        await client.call_tool("append_note", {"name": "journal", "content": "day 2"})
        r = await client.call_tool("read_note", {"name": "journal"})
        assert r.structured_content["result"] == "day 1\n\nday 2\n"

        await client.call_tool(
            "log_progress",
            {"summary": "8 words reviewed, 2 sessions", "heading": "This week"},
        )
        progress = (await client.call_tool("read_note", {"name": "progress"})).structured_content[
            "result"
        ]
        assert "## " in progress and "This week" in progress

        listed = (await client.call_tool("list_notes", {})).structured_content["result"]
        assert {n["name"] for n in listed} == {"journal.md", "progress.md"}

        # error is reported, session survives
        bad = await client.call_tool("read_note", {"name": "../../etc/hosts"})
        assert bad.is_error is True
        again = await client.call_tool("list_notes", {})
        assert again.is_error is False

    asyncio.run(_run(scenario))
