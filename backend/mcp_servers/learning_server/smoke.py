"""Standalone smoke session for MCP server #1 -- run without the agent.

    python -m backend.mcp_servers.learning_server.smoke

Connects a real MCP ``ClientSession`` to the server over an in-memory transport
and walks a full study flow (list tools + resources, read a resource, compose a
session, quiz, grade, update state), printing a transcript. The pytest version
lives in backend/mcp_servers/tests/test_standalone_client.py; this is the
human-readable equivalent of an MCP Inspector run.

Point DATABASE_URL at a seeded DB first, e.g.:
    DATABASE_URL=sqlite+pysqlite:///local.db python -m backend.db.seed
"""

from __future__ import annotations

import asyncio
import json

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from backend.mcp_servers.learning_server.server import build_server


def _show(label: str, value: object) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    print(f"  {label}: {text[:300]}")


async def _session(user_id: int) -> None:
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        server = build_server()._lowlevel_server
        async with anyio.create_task_group() as tg:

            async def _serve():
                await server.run(
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                )

            tg.start_soon(_serve)
            async with ClientSession(client_streams[0], client_streams[1]) as client:
                await client.initialize()

                print("== tools ==")
                for tool in (await client.list_tools()).tools:
                    print(f"  {tool.name}")

                print("== resources ==")
                for res in (await client.list_resources()).resources:
                    print(f"  {res.uri}")
                for tmpl in (await client.list_resource_templates()).resource_templates:
                    print(f"  {tmpl.uri_template}")

                print("== vocab://words ==")
                _show("overview", (await client.read_resource("vocab://words")).contents[0].text)

                print(f"== study flow for user {user_id} ==")
                profile = await client.call_tool("get_user_profile", {"user_id": user_id})
                _show("profile", profile.structured_content)

                session = await client.call_tool(
                    "create_learning_session", {"user_id": user_id, "minutes_available": 10}
                )
                sv = session.structured_content
                _show("session", {k: sv[k] for k in ("session_id", "topic")})
                word_ids = [w["id"] for w in (sv["review_words"] + sv["new_words"])][:3]

                quiz = await client.call_tool(
                    "create_quiz", {"word_ids": word_ids, "quiz_type": "en_to_de"}
                )
                questions = quiz.structured_content["result"]
                for q in questions:
                    _show("q", {"prompt": q["prompt"], "hint": q["hint"]})

                if questions:
                    first = questions[0]
                    graded = await client.call_tool(
                        "evaluate_answer",
                        {"question_id": first["question_id"], "user_answer": "totally wrong"},
                    )
                    _show("graded", graded.structured_content)
                    updated = await client.call_tool(
                        "update_learning_state",
                        {"user_id": user_id, "word_id": first["word_id"], "correct": False},
                    )
                    _show("new state", updated.structured_content)

            tg.cancel_scope.cancel()


def main() -> None:
    asyncio.run(_session(user_id=1))


if __name__ == "__main__":
    main()
