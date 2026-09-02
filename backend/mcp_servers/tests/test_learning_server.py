"""MCP server #1 -- tool discovery + invocation (LG-06).

Calls run in-process via ``server.call_tool``; the standalone MCP-client /
Inspector session is LG-08.
"""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from backend.mcp_servers.learning_server.server import MAX_LIMIT, build_server
from backend.tracing.tracer import Tracer


def _call(name: str, args: dict):
    return asyncio.run(build_server().call_tool(name, args))


def test_tool_manifest():
    tools = asyncio.run(build_server().list_tools())
    names = {t.name for t in tools}
    assert names == {
        "get_user_profile",
        "get_words_due_for_review",
        "get_weak_words",
        "get_new_words",
        "create_learning_session",
        "finish_learning_session",
        "create_quiz",
        "evaluate_answer",
        "update_learning_state",
    }
    for t in tools:
        assert t.description
        assert t.output_schema is not None


def test_get_user_profile_shape(seeded_db):
    res = _call("get_user_profile", {"user_id": 1})
    assert res.is_error is False
    p = res.structured_content
    assert p["user_id"] == 1
    assert p["target"] == "work"
    assert p["total_reviews"] == 3
    assert p["words_seen"] == 2
    assert p["cefr_ceiling"] == "A2"  # word 2 (A1) answered correctly
    assert p["overall_accuracy"] == pytest.approx(1 / 3, abs=1e-4)


def test_get_user_profile_unknown_user_is_tool_error(seeded_db):
    with pytest.raises(ToolError):
        _call("get_user_profile", {"user_id": 404})


def test_get_weak_words(seeded_db):
    rows = _call("get_weak_words", {"user_id": 1, "limit": 5}).structured_content["result"]
    assert [r["id"] for r in rows][:1] == [1]  # two failures -> weakest
    assert all("translation_en" in r for r in rows)


def test_get_new_words_excludes_seen_and_filters_topic(seeded_db):
    rows = _call("get_new_words", {"user_id": 1, "topic": "food", "count": 10})
    ids = [r["id"] for r in rows.structured_content["result"]]
    assert ids == [3, 7, 12]  # food words, word 3 unseen (only 1 & 2 seen)


def test_get_words_due_for_review(seeded_db):
    rows = _call("get_words_due_for_review", {"user_id": 1}).structured_content["result"]
    # both seen words are long overdue (fixture timestamps are in the past);
    # word 2 (due T0+1d) sorts before word 1 (due T0+2d, after its 2nd failure).
    assert [r["id"] for r in rows] == [2, 1]


def test_limit_is_clamped(seeded_db):
    # count above MAX_LIMIT must not raise
    res = _call("get_new_words", {"user_id": 1, "count": MAX_LIMIT + 10_000})
    assert res.is_error is False


# --- LG-07: session + quiz + grading + state ---------------------------------


def test_create_learning_session_persists_and_hydrates(seeded_db):
    sv = _call(
        "create_learning_session", {"user_id": 1, "minutes_available": 15}
    ).structured_content
    assert sv["session_id"] == 1
    assert sv["review_words"] and sv["review_words"][0]["lemma"]  # word 1 or 2 due
    assert isinstance(sv["new_words"], list)
    ids = {w["id"] for w in sv["review_words"] + sv["new_words"]}
    assert len(ids) == len(sv["review_words"]) + len(sv["new_words"])  # no dupes


def test_create_learning_session_unknown_user(seeded_db):
    with pytest.raises(ToolError):
        _call("create_learning_session", {"user_id": 77, "minutes_available": 10})


def test_finish_learning_session_records_words_covered(seeded_db):
    sv = _call("create_learning_session", {"user_id": 1, "minutes_available": 10})
    sid = sv.structured_content["session_id"]

    summary = _call(
        "finish_learning_session", {"session_id": sid, "words_covered": 4}
    ).structured_content
    assert summary["session_id"] == sid
    assert summary["words_covered"] == 4
    assert summary["user_id"] == 1

    with pytest.raises(ToolError):
        _call("finish_learning_session", {"session_id": 9999, "words_covered": 1})


def test_quiz_roundtrip_en_to_de(seeded_db):
    quiz = _call("create_quiz", {"word_ids": [3, 4], "quiz_type": "en_to_de"})
    questions = quiz.structured_content["result"]
    assert len(questions) == 2
    qid = questions[0]["question_id"]

    ev = _call("evaluate_answer", {"question_id": qid, "user_answer": "wort3"}).structured_content
    assert ev["correct"] is True
    assert ev["method"] == "exact"
    assert ev["word_id"] == 3
    assert ev["expected"] == "wort3"

    wrong = _call(
        "evaluate_answer", {"question_id": qid, "user_answer": "totallywrong"}
    ).structured_content
    assert wrong["correct"] is False


def test_quiz_article_skips_non_nouns(seeded_db):
    # fixture: odd ids are nouns (article "das"), even ids are not
    quiz = _call("create_quiz", {"word_ids": [1, 2, 3], "quiz_type": "article"})
    questions = quiz.structured_content["result"]
    assert [q["word_id"] for q in questions] == [1, 3]
    assert questions[0]["options"] == ["der", "die", "das"]


def test_evaluate_answer_de_to_en_falls_back_without_llm(seeded_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")
    quiz = _call("create_quiz", {"word_ids": [3], "quiz_type": "de_to_en"})
    qid = quiz.structured_content["result"][0]["question_id"]
    ev = _call("evaluate_answer", {"question_id": qid, "user_answer": "word 3"}).structured_content
    assert ev["method"] == "semantic_fallback_fuzzy"
    assert ev["correct"] is True


def test_evaluate_answer_rejects_bad_question_id(seeded_db):
    with pytest.raises(ToolError):
        _call("evaluate_answer", {"question_id": "not-a-qid", "user_answer": "x"})


def test_update_learning_state_records_and_returns_new_state(seeded_db):
    state = _call(
        "update_learning_state", {"user_id": 1, "word_id": 5, "correct": True}
    ).structured_content
    assert state["word_id"] == 5
    assert state["repetitions"] == 1
    assert state["interval_days"] == 1
    assert state["due_at"] is not None


def test_update_learning_state_unknown_word(seeded_db):
    with pytest.raises(ToolError):
        _call("update_learning_state", {"user_id": 1, "word_id": 9999, "correct": True})


# --- LG-08: tracing + vocab resource ---------------------------------------


def test_every_tool_call_is_traced(seeded_db, tmp_path):
    trace_path = tmp_path / "t.jsonl"
    server = build_server(tracer=Tracer(trace_path))

    asyncio.run(server.call_tool("get_user_profile", {"user_id": 1}))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("get_user_profile", {"user_id": 999}))

    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [e["name"] for e in events] == [
        "learning.tool.get_user_profile",
        "learning.tool.get_user_profile",
    ]
    ok, failed = events
    assert ok["success"] is True and ok["output"] and ok["latency_ms"] >= 0
    assert ok["input"] == {"user_id": 1}
    assert failed["success"] is False and failed["error"]


def test_vocab_resources(seeded_db):
    server = build_server()

    index = asyncio.run(server.read_resource("vocab://words"))
    overview = json.loads(index[0].content)
    assert overview["total"] == 30
    assert overview["by_cefr_level"]["A1"] == 10
    assert "vocab://word/{lemma}" in overview["resource_templates"]

    a2 = asyncio.run(server.read_resource("vocab://words/a2"))  # case-insensitive
    rows = json.loads(a2[0].content)
    assert len(rows) == 10 and all(w["cefr_level"] == "A2" for w in rows)

    one = json.loads(asyncio.run(server.read_resource("vocab://word/WORT7"))[0].content)
    assert one["lemma"] == "wort7"
