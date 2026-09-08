"""A thin client the agent uses to reach MCP server #1.

The agent touches the data layer only through typed MCP tool calls -- even
in-process (a core design rule). This wraps an ``MCPServer`` and exposes
two things the orchestrator needs: Anthropic-shaped tool specs, and a sync
``call(name, args)`` that traces every call.

Swapping the in-process server for a real transport client later means
re-implementing this class only; the orchestrator does not change.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from backend.mcp_servers.learning_server.server import build_server
from backend.tracing.tracer import Tracer, get_tracer

_PREVIEW = 400


class MCPToolError(RuntimeError):
    """A tool returned an error result / raised inside the server."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


def _payload(result: Any) -> Any:
    """Unwrap a CallToolResult to plain data. List tools come back wrapped as
    ``{"result": [...]}``; flatten that."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    # Fall back to concatenated text blocks.
    return "".join(getattr(b, "text", "") for b in getattr(result, "content", []))


def _preview(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= _PREVIEW else text[:_PREVIEW] + "..."


class MCPToolClient:
    def __init__(self, server=None, *, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or get_tracer()
        # Share the tracer so server-side (learning.tool.*) and agent-side
        # (agent.tool_call.*) events land in the same log.
        self._server = server or build_server(tracer=self._tracer)
        self.name = self._server.name  # "learning" | "notes" | ...

    def tool_specs(self) -> list[dict]:
        """Tool definitions in Anthropic Messages API shape."""
        tools = asyncio.run(self._server.list_tools())
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def call(self, name: str, arguments: dict | None = None) -> Any:
        arguments = arguments or {}
        with self._tracer.trace_tool_call(f"agent.tool_call.{name}", arguments) as box:
            try:
                result = asyncio.run(self._server.call_tool(name, arguments))
            except ToolError as exc:
                raise MCPToolError(name, str(exc)) from exc
            if getattr(result, "is_error", False):
                raise MCPToolError(name, _payload(result))
            payload = _payload(result)
            box["output"] = _preview(payload)
            return payload


class MultiServerToolClient:
    """Presents several MCP servers as one tool surface for the agent.

    Same duck-typed interface as ``MCPToolClient`` (``tool_specs`` / ``call``),
    so ``run_session`` / ``run_conversation`` don't care how many servers there
    are. Tool names are assumed unique across servers (they are, for this
    project's two).
    """

    def __init__(self, clients: list[MCPToolClient]) -> None:
        self._clients = list(clients)
        self._route: dict[str, MCPToolClient] = {}
        for client in self._clients:
            for spec in client.tool_specs():
                self._route.setdefault(spec["name"], client)

    def tool_specs(self) -> list[dict]:
        specs: list[dict] = []
        seen: set[str] = set()
        for client in self._clients:
            for spec in client.tool_specs():
                if spec["name"] not in seen:
                    seen.add(spec["name"])
                    specs.append(spec)
        return specs

    def server_for(self, name: str) -> str | None:
        client = self._route.get(name)
        return client.name if client else None

    def call(self, name: str, arguments: dict | None = None) -> Any:
        client = self._route.get(name)
        if client is None:
            raise MCPToolError(name, "no MCP server exposes this tool")
        return client.call(name, arguments)


def build_default_clients(*, tracer: Tracer | None = None) -> MultiServerToolClient:
    """The standard pair: learning server #1 + notes server #2, one shared tracer."""
    from backend.mcp_servers.secondary_server.server import build_server as build_notes_server

    tracer = tracer or get_tracer()
    return MultiServerToolClient(
        [
            MCPToolClient(build_server(tracer=tracer), tracer=tracer),
            MCPToolClient(build_notes_server(tracer=tracer), tracer=tracer),
        ]
    )
