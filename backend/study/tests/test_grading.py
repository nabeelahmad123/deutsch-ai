"""Answer grading: normalisation, fuzzy match, dispatcher, LLM fallback."""

from dataclasses import dataclass

import pytest

from backend.study.grading import (
    GradeResult,
    diagnose,
    fuzzy_match,
    grade,
    normalize,
    semantic_grade,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Das Haus ", "haus"),
        ("to go", "go"),
        ("the Book!", "book"),
        ("Ärger", "ärger"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_fuzzy_match_exact_and_close():
    assert fuzzy_match("Haus", "das Haus") == (True, 1.0)
    ok, _score = fuzzy_match("Haos", "Haus")  # one-char typo, rescued by edit distance
    assert ok
    assert fuzzy_match("Auto", "Haus")[0] is False  # 3 edits -> not close


def test_fuzzy_match_multi_sense_reference():
    ok, _ = fuzzy_match("journey", "journey, travel")
    assert ok
    ok2, _ = fuzzy_match("banana", "journey, travel")
    assert not ok2


def test_grade_en_to_de_exact_then_fuzzy():
    assert grade("en_to_de", "Haus", "haus").method == "exact"
    r = grade("en_to_de", "Haus", "Haos")
    assert r.correct and r.method == "fuzzy"
    assert grade("en_to_de", "Haus", "Auto").correct is False


def test_grade_multiple_choice_is_exact_only():
    assert grade("multiple_choice", "house", "  House ").correct is True
    assert grade("multiple_choice", "house", "hous").correct is False


def test_grade_de_to_en_falls_back_to_fuzzy_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")  # ensure no real call
    r = grade("de_to_en", "house", "house")
    assert r.method == "semantic_fallback_fuzzy"
    assert r.correct is True  # fuzzy still matches


def test_diagnose_correct_answer_has_no_error():
    d = diagnose("en_to_de", "Haus", "Haus", correct=True)
    assert d.error_type is None and d.feedback == ""


def test_diagnose_blank():
    assert diagnose("en_to_de", "Haus", "   ", correct=False).error_type == "blank"


def test_diagnose_article_quiz_is_always_gender():
    d = diagnose("article", "das", "der", correct=False)
    assert d.error_type == "wrong_gender" and "das" in d.feedback


def test_diagnose_en_to_de_wrong_article():
    d = diagnose("en_to_de", "Haus", "der Haus", correct=False, article="das")
    assert d.error_type == "wrong_gender" and "das Haus" in d.feedback


def test_diagnose_en_to_de_plural_for_singular():
    d = diagnose("en_to_de", "Haus", "Häuser", correct=False, article="das", plural="Häuser")
    assert d.error_type == "wrong_plural"


def test_diagnose_en_to_de_spelling_near_miss():
    d = diagnose("en_to_de", "Wetter", "Weter", correct=False)
    assert d.error_type == "spelling"


def test_diagnose_wrong_word_falls_back_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")
    d = diagnose("en_to_de", "Haus", "Auto", correct=False)
    assert d.error_type == "other" and d.method == "semantic_fallback"


def test_diagnose_uses_supplied_client_for_meaning_errors():
    @dataclass
    class _Block:
        type: str
        text: str

    class _Msg:
        content = [
            _Block("text", '{"error_type": "false_friend", "feedback": "gift means poison"}')
        ]

    class _FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                return _Msg()

    d = diagnose("de_to_en", "poison", "present", correct=False, client=_FakeClient())
    assert d.error_type == "false_friend" and d.method == "semantic"


def test_grade_de_to_en_uses_semantic_client_when_supplied():
    @dataclass
    class _Block:
        type: str
        text: str

    class _Msg:
        content = [_Block("text", '{"correct": true, "score": 0.9, "rationale": "close enough"}')]

    class _Messages:
        def create(self, **kwargs):
            assert kwargs["model"] and kwargs["messages"]
            return _Msg()

    class _FakeClient:
        messages = _Messages()

    r = semantic_grade("q", "house", "a house", client=_FakeClient())
    assert r == GradeResult(True, 0.9, "close enough", "semantic")

    r2 = grade("de_to_en", "house", "a house", client=_FakeClient())
    assert r2.method == "semantic"
