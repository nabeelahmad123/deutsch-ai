"""Conversational-practice composition, tutor turn parsing, and SR feedback."""

import datetime as dt
from dataclasses import dataclass

import pytest

from backend.core import scheduler
from backend.study import conversation
from backend.study.conversation import (
    TutorReply,
    _split_used,
    compose_targets,
    finish_conversation,
    tutor_turn,
)

from .conftest import T0

DAY = dt.timedelta(days=1)


def test_split_used_parses_the_used_line():
    reply, used = _split_used(
        "Guten Tag! Was möchten Sie trinken?\nUSED: der Kaffee, Tag, banane",
        ["Kaffee", "Tag", "Wasser"],
    )
    assert reply == "Guten Tag! Was möchten Sie trinken?"
    assert used == ["Kaffee", "Tag"]  # article stripped, unknown 'banane' dropped


def test_split_used_none_and_missing_line():
    assert _split_used("Nur Deutsch.\nUSED: NONE", ["Kaffee"]) == ("Nur Deutsch.", [])
    assert _split_used("Kein Marker hier.", ["Kaffee"]) == ("Kein Marker hier.", [])


def test_tutor_turn_with_a_fake_client():
    @dataclass
    class _Block:
        type: str
        text: str

    class _FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                assert "café" in kwargs["system"] or "Café" in kwargs["system"]
                return type(
                    "M", (), {"content": [_Block("text", "Und zum Trinken?\nUSED: Kaffee")]}
                )

    r = tutor_turn(
        "cafe", "A2", ["Kaffee", "Tee"], [], "Ich möchte einen Kaffee.", client=_FakeClient()
    )
    assert isinstance(r, TutorReply) and r.available
    assert r.reply == "Und zum Trinken?" and r.used_lemmas == ["Kaffee"]


def test_tutor_turn_degrades_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")
    r = tutor_turn("cafe", "A1", ["Kaffee"], [], "Hallo")
    assert r.available is False and "nicht verfügbar" in r.reply and r.used_lemmas == []


def test_compose_targets_prefers_due_then_weak_then_new(session):
    # word 1 reviewed wrong -> due tomorrow + weak; others unseen
    scheduler.update_after_review(session, 1, 1, correct=False, response_time_ms=9000, as_of=T0)
    targets = compose_targets(session, 1, count=5)
    ids = [w.id for w in targets]
    assert ids[0] == 1  # the due/weak word leads
    assert len(ids) == 5 and len(set(ids)) == 5  # filled with new, no dups


def test_finish_conversation_records_a_correct_review_for_used_words(session):
    plan = scheduler.create_learning_session(session, 1, 10, "cafe", as_of=T0)
    out = finish_conversation(session, plan.session_id, 1, [2, 3, 2], turns=6)
    assert out["words_practised"] == 2  # 2 and 3, de-duped
    assert out["turns"] == 6
    st = scheduler.get_card_state(session, 1, 2)
    assert st.repetitions == 1  # one correct review landed


def test_start_conversation_unknown_user(session):
    with pytest.raises(LookupError):
        conversation.start_conversation(session, 999, "cafe", 10)
