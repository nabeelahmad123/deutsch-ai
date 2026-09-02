"""MCP server #2 -- a Markdown notes vault (CLAUDE.md section 10).

A genuinely separate tool surface from server #1 (non-negotiable principle #5):
its own process, its own transport/port, its own storage (the filesystem, not
Postgres), and no imports from the learning server or backend.core. The agent is
the only thing that spans both -- e.g. read progress from server #1, then
``log_progress`` here.

Every tool call is traced (principle #4).
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backend.mcp_servers.secondary_server import vault
from backend.tracing.tracer import Tracer

INSTRUCTIONS = (
    "A Markdown notes vault. Read/write/append free-form notes, and log_progress "
    "to append a dated section to progress.md -- use it to record a study "
    "summary. Note names are safe relative paths ('.md' optional)."
)
_PREVIEW = 400


def _preview(result: Any) -> Any:
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    if isinstance(result, list):
        return {"count": len(result), "first": _preview(result[0]) if result else None}
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return text if len(text) <= _PREVIEW else text[:_PREVIEW] + "..."


def build_server(*, tracer: Tracer | None = None) -> MCPServer:
    server = MCPServer("notes", instructions=INSTRUCTIONS)
    tracer = tracer or Tracer()

    def traced(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with tracer.trace_tool_call(f"notes.tool.{fn.__name__}", kwargs or list(args)) as box:
                result = fn(*args, **kwargs)
                box["output"] = _preview(result)
                return result

        return wrapper

    @server.tool()
    @traced
    def list_notes() -> list[vault.NoteInfo]:
        """List every note in the vault (name, size, last modified)."""
        return vault.list_notes()

    @server.tool()
    @traced
    def read_note(name: str) -> str:
        """Return the Markdown contents of a note."""
        try:
            return vault.read_note(name)
        except vault.VaultError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    @traced
    def write_note(name: str, content: str) -> vault.NoteInfo:
        """Create or overwrite a note."""
        try:
            return vault.write_note(name, content)
        except vault.VaultError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    @traced
    def append_note(name: str, content: str) -> vault.NoteInfo:
        """Append to a note, creating it if needed."""
        try:
            return vault.append_note(name, content)
        except vault.VaultError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    @traced
    def log_progress(
        summary: str, heading: str | None = None, date: str | None = None
    ) -> vault.ProgressEntry:
        """Append a dated section to progress.md -- a study-progress summary.
        date defaults to today (ISO); heading defaults to 'Progress'."""
        return vault.log_progress(summary, heading=heading, date=date)

    return server
