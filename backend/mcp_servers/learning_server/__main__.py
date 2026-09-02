"""MCP server #1 -- learning tools (CLAUDE.md section 8).

Built with the official MCP Python SDK. Exposes as TOOLS:
  get_user_profile, get_words_due_for_review, get_weak_words, get_new_words,
  create_quiz, evaluate_answer, update_learning_state, create_learning_session
and the vocab table as an MCP RESOURCE.

Every tool wraps the deterministic core in ``backend/core`` -- the agent reaches
the data layer only through here (non-negotiable principle #3). Runs as its own
process (principle #5).

Day-1 status: stub entrypoint. This is build-order step 3; it must be tested
standalone against an MCP client before the agent depends on it.
"""

from __future__ import annotations

import os


def main() -> None:
    port = os.environ.get("LEARNING_MCP_PORT", "8100")
    raise SystemExit(
        f"learning MCP server not implemented yet (build-order step 3). " f"Would bind port {port}."
    )


if __name__ == "__main__":
    main()
