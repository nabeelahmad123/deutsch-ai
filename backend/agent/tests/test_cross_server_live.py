"""Real Anthropic-API cross-server run. Skipped unless a key is present.

ANTHROPIC_API_KEY=... uv run pytest backend/agent/tests/test_cross_server_live.py
"""

import os

import pytest

from backend.agent.orchestrator import SessionRequest, run_conversation

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="no ANTHROPIC_API_KEY; live cross-server test skipped",
)


def test_compose_then_log_progress_spans_both_servers(seeded_db, tmp_path, vault_path):
    result = run_conversation(
        SessionRequest(
            raw_text="Give me a 10-minute German work session, then note where I'm at",
            user_id=1,
        )
    )
    assert result.stopped == "completed"
    assert set(result.servers_used) == {"learning", "notes"}
    assert "create_learning_session" in result.tool_calls
    assert (vault_path / "progress.md").exists()
