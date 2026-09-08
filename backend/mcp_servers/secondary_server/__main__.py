"""Entry point for MCP server #2 -- the notes vault.

Its own process, its own transport (a core design rule). Transport
defaults to stdio; set SECONDARY_MCP_TRANSPORT=streamable-http to serve over HTTP
on SECONDARY_MCP_HOST:SECONDARY_MCP_PORT (what docker-compose uses).

SECONDARY_MCP_KIND selects the surface -- "notes" (implemented) or "calendar"
a calendar server was the alternative, not built.
"""

from __future__ import annotations

import os

from backend.mcp_servers.secondary_server.server import build_server


def main() -> None:
    kind = os.environ.get("SECONDARY_MCP_KIND", "notes")
    if kind == "calendar":
        raise SystemExit(
            "SECONDARY_MCP_KIND=calendar is not implemented; this project ships the "
            "notes surface. Set SECONDARY_MCP_KIND=notes."
        )
    if kind != "notes":
        raise SystemExit(f"unknown SECONDARY_MCP_KIND={kind!r} (expected 'notes' or 'calendar')")

    server = build_server()
    transport = os.environ.get("SECONDARY_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=os.environ.get("SECONDARY_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("SECONDARY_MCP_PORT", "8101")),
        )


if __name__ == "__main__":
    main()
