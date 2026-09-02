"""Real Anthropic-API run of the orchestrator. Skipped unless a key is present;
run it manually to confirm the loop works end to end against a live model.

    ANTHROPIC_API_KEY=... uv run pytest backend/agent/tests/test_orchestrator_live.py
"""

import os

import pytest

from backend.agent.orchestrator import SessionRequest, run_session

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="no ANTHROPIC_API_KEY; live agent test skipped",
)


def test_ten_minutes_for_work_composes_a_session(seeded_db):
    result = run_session(
        SessionRequest(raw_text="I've got 10 minutes, learning German for work", user_id=1)
    )
    assert result.stopped == "completed"
    assert "create_learning_session" in result.tool_calls
    assert result.intent["minutes_available"] == 10
    assert result.session_id is not None
