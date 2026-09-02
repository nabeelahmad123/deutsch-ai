"""MCP server #2 -- second, independent tool surface (CLAUDE.md section 10).

Pick one (env ``SECONDARY_MCP_KIND``):
  - "notes"    : export a weekly progress summary to a markdown vault
  - "calendar" : schedule recurring study sessions

A genuinely separate process/service from server #1, on its own transport
(non-negotiable principle #5). The agent must be able to use both in one
conversation ("set up daily 10-minute sessions this week and remind me Monday").

Day-1 status: stub entrypoint. This is build-order step 5.
"""

from __future__ import annotations

import os


def main() -> None:
    kind = os.environ.get("SECONDARY_MCP_KIND", "notes")
    port = os.environ.get("SECONDARY_MCP_PORT", "8101")
    if kind not in {"notes", "calendar"}:
        raise SystemExit(f"unknown SECONDARY_MCP_KIND={kind!r} (expected 'notes' or 'calendar')")
    raise SystemExit(
        f"secondary MCP server ({kind}) not implemented yet (build-order step 5). "
        f"Would bind port {port}."
    )


if __name__ == "__main__":
    main()
