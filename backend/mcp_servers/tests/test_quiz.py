"""Quiz question construction + self-contained question ids."""

import pytest

from backend.core.read_models import WordView
from backend.mcp_servers.learning_server.quiz import (
    build_question,
    decode_qid,
    encode_qid,
)

NOUN = WordView(1, "Haus", "das", "Häuser", "house", "A1", "home", "haʊ̯s")
VERB = WordView(2, "gehen", None, None, "to go", "A1", None, "ˈɡeːən")


def test_qid_roundtrips():
    spec = {"w": 1, "t": "en_to_de", "r": "Haus", "p": "Translate to German: house"}
    assert decode_qid(encode_qid(spec)) == spec


@pytest.mark.parametrize("bad", ["", "nope", "q1:!!!!", "q1:" + "eyJ4Ijo"])
def test_decode_qid_rejects_garbage(bad):
    with pytest.raises(ValueError):
        decode_qid(bad)


def test_en_to_de_question():
    q = build_question(NOUN, "en_to_de")
    assert q.quiz_type == "en_to_de"
    assert q.prompt == "Translate to German: house"
    assert q.options is None
    assert decode_qid(q.question_id)["r"] == "Haus"


def test_de_to_en_question_shows_article():
    q = build_question(NOUN, "de_to_en")
    assert q.prompt == "Translate to English: das Haus"
    assert decode_qid(q.question_id)["r"] == "house"


def test_article_question_only_for_nouns():
    q = build_question(NOUN, "article")
    assert q.options == ["der", "die", "das"]
    assert decode_qid(q.question_id)["r"] == "das"
    assert build_question(VERB, "article") is None


def test_multiple_choice_includes_answer_and_is_deterministic():
    q1 = build_question(NOUN, "multiple_choice", ["dog", "tree", "water"])
    q2 = build_question(NOUN, "multiple_choice", ["dog", "tree", "water"])
    assert set(q1.options) == {"house", "dog", "tree", "water"}
    assert q1.options == q2.options  # seeded by word id


def test_unknown_quiz_type_raises():
    with pytest.raises(ValueError):
        build_question(NOUN, "bogus")
