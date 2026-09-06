"""Without Anthropic credentials the agent fails fast with a clear message
rather than a raw SDK traceback (CLAUDE.md section 11: never crash silently)."""

import pytest

from backend.agent.mcp_client import MCPToolClient
from backend.agent.orchestrator import MissingAPIKey, SessionRequest, run_session


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def test_anthropic_client_requires_a_key():
    from backend.agent.orchestrator import _anthropic_client

    with pytest.raises(MissingAPIKey, match="ANTHROPIC_API_KEY"):
        _anthropic_client()


def test_run_session_without_a_key_raises_missing_api_key(tmp_path):
    with pytest.raises(MissingAPIKey):
        run_session(
            SessionRequest(raw_text="I have 10 minutes, German for work", user_id=1),
            mcp_client=MCPToolClient(),
        )


def test_cli_reports_missing_key_without_a_traceback(monkeypatch):
    from backend.agent.__main__ import main

    monkeypatch.setattr("sys.argv", ["backend.agent", "I have 10 minutes, German for work"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert "agent unavailable" in str(exc.value)
