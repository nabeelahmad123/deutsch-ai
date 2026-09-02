"""Entry point for MCP server #1 -- learning tools (CLAUDE.md section 8).

Runs as its own process (non-negotiable principle #5). Transport defaults to
stdio (easiest for the MCP Inspector / Claude Desktop / standalone testing);
set LEARNING_MCP_TRANSPORT=streamable-http to serve over HTTP on
LEARNING_MCP_HOST:LEARNING_MCP_PORT (what docker-compose uses).
"""

from __future__ import annotations

import os

from backend.mcp_servers.learning_server.server import build_server


def main() -> None:
    server = build_server()
    transport = os.environ.get("LEARNING_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=os.environ.get("LEARNING_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("LEARNING_MCP_PORT", "8100")),
        )


if __name__ == "__main__":
    main()
