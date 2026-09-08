"""The /agent/plan endpoint: key-gating, rate limiting, and result relay.

The agent's LLM loop is replaced with a stub -- this tests the API surface, not
the orchestrator (that has its own suite).
"""

from __future__ import annotations

import pytest

from backend.agent.orchestrator import ConversationResult, SessionResult
from backend.api import agent as agent_api


@pytest.fixture(autouse=True)
def _reset_guards(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    agent_api._client_hits.clear()
    agent_api._day_bucket[0], agent_api._day_bucket[1] = "", 0
    yield
    agent_api._client_hits.clear()


def _fake_session(**over):
    base = dict(
        stopped="completed",
        intent={"minutes_available": 10, "topic": "work"},
        session_id=1,
        review_words=[{"id": 2, "lemma": "Haus"}],
        new_words=[{"id": 4, "lemma": "Arbeit"}],
        quiz=[{"question_id": "q:abc", "prompt": "the house", "hint": None}],
        tool_calls=["get_user_profile", "create_learning_session", "create_quiz"],
        turns=3,
        reply="A 10-minute work session: 1 review, 1 new word.",
    )
    base.update(over)
    return SessionResult(**base)


def test_plan_relays_the_agent_result(client, monkeypatch):
    monkeypatch.setattr(agent_api, "run_session", lambda req: _fake_session())
    r = client.post("/agent/plan", json={"user_id": 1, "request": "10 minutes, German for work"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "plan"
    assert body["tool_calls"] == ["get_user_profile", "create_learning_session", "create_quiz"]
    assert body["intent"]["minutes_available"] == 10
    assert body["session_id"] == 1
    assert body["reply"].startswith("A 10-minute")


def test_converse_mode_reports_servers_used(client, monkeypatch):
    monkeypatch.setattr(
        agent_api,
        "run_conversation",
        lambda req: ConversationResult(
            stopped="completed",
            turns=4,
            reply="Session set up and progress noted.",
            tool_calls=["create_learning_session", "log_progress"],
            servers_used=["learning", "notes"],
        ),
    )
    r = client.post(
        "/agent/plan",
        json={"user_id": 1, "request": "set up a session and note progress", "mode": "converse"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "converse"
    assert body["servers_used"] == ["learning", "notes"]


def test_503_without_a_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = client.post("/agent/plan", json={"user_id": 1, "request": "10 minutes work"})
    assert r.status_code == 503


def test_rate_limited_per_client(client, monkeypatch):
    monkeypatch.setattr(agent_api, "run_session", lambda req: _fake_session())
    body = {"user_id": 1, "request": "10 minutes, German for work"}
    for _ in range(agent_api._PER_CLIENT):
        assert client.post("/agent/plan", json=body).status_code == 200
    blocked = client.post("/agent/plan", json=body)
    assert blocked.status_code == 429
    assert "slow down" in blocked.json()["detail"]


def test_agent_failure_becomes_502(client, monkeypatch):
    def boom(_req):
        raise RuntimeError("mcp exploded")

    monkeypatch.setattr(agent_api, "run_session", boom)
    r = client.post("/agent/plan", json={"user_id": 1, "request": "10 minutes work"})
    assert r.status_code == 502
    assert "the agent failed" in r.json()["detail"]


def test_request_validation(client):
    assert client.post("/agent/plan", json={"user_id": 1, "request": "hi"}).status_code == 422
    assert (
        client.post(
            "/agent/plan", json={"user_id": 1, "request": "ok go", "mode": "bogus"}
        ).status_code
        == 422
    )
