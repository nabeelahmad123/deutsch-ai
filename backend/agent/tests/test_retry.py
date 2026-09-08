"""_create_message retries transient API failures, then gives up."""

from __future__ import annotations

import pytest

from backend.agent import orchestrator as orch


class _Transient(Exception):
    pass


class _FlakyMessages:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def create(self, **_kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _Transient("overloaded")
        return "ok"


class _Flaky:
    def __init__(self, fail_times: int) -> None:
        self.messages = _FlakyMessages(fail_times)


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(orch, "_TRANSIENT_EXC", (_Transient,))
    monkeypatch.setattr(orch.time, "sleep", lambda _s: None)


def test_recovers_after_transient_failures():
    llm = _Flaky(fail_times=2)
    assert orch._create_message(llm) == "ok"
    assert llm.messages.calls == 3


def test_gives_up_after_the_attempt_budget():
    llm = _Flaky(fail_times=99)
    with pytest.raises(_Transient):
        orch._create_message(llm)
    assert llm.messages.calls == orch._RETRY_ATTEMPTS


def test_non_transient_error_is_not_retried():
    class _Boom:
        class messages:  # noqa: N801
            @staticmethod
            def create(**_kw):
                raise ValueError("bad request")

    with pytest.raises(ValueError):
        orch._create_message(_Boom())
