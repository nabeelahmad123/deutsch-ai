"""LG-10: the full section-9 flow -- compose, quiz, grade each answer, summarise.

The LLM is scripted (no network); grading falls back to fuzzy matching since no
ANTHROPIC_API_KEY is set, which is enough to exercise the orchestration.
"""

import base64
import json

from backend.agent.mcp_client import MCPToolClient
from backend.agent.orchestrator import SessionRequest, start_session
from backend.tracing.tracer import Tracer

from .fake_llm import FakeLLM, response, text_block, tool_use


def _script():
    return [
        response(tool_use("get_user_profile", {"user_id": 1})),
        response(
            tool_use(
                "create_learning_session",
                {"user_id": 1, "minutes_available": 10, "topic": "work"},
            )
        ),
        response(tool_use("create_quiz", {"word_ids": [2, 4], "quiz_type": "en_to_de"})),
        response(text_block("Ready."), stop_reason="end_turn"),
    ]


def _start(tmp_path):
    tracer = Tracer(tmp_path / "trace.jsonl")
    sess = start_session(
        SessionRequest(raw_text="10 minutes, German for work", user_id=1),
        mcp_client=MCPToolClient(tracer=tracer),
        llm_client=FakeLLM(_script()),
        tracer=tracer,
    )
    return sess, tracer


def test_compose_answer_and_summarise(seeded_db, tmp_path):
    sess, _ = _start(tmp_path)
    assert sess.session_id == 1
    assert len(sess.quiz) == 2

    q0, q1 = sess.quiz
    # decode the self-contained qid to learn the expected answer (its lemma)
    right_lemma = json.loads(base64.urlsafe_b64decode(q0["question_id"].split(":", 1)[1]))["r"]

    fb0 = sess.answer(q0["question_id"], right_lemma)
    assert fb0.correct is True
    assert fb0.new_state["repetitions"] == 1  # update_learning_state applied

    fb1 = sess.answer(q1["question_id"], "definitely not the word")
    assert fb1.correct is False

    summary = sess.summary()
    assert summary["answered"] == 2
    assert summary["correct"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["session_row"]["words_covered"] == 2  # persisted


def test_answer_traces_evaluate_then_update(seeded_db, tmp_path):
    sess, tracer = _start(tmp_path)
    sess.answer(sess.quiz[0]["question_id"], "irrelevant")

    events = [json.loads(x) for x in tracer.path.read_text().splitlines()]
    agent_calls = [e["name"] for e in events if e["name"].startswith("agent.tool_call.")]
    # planning calls, then the grade sequence in order
    assert agent_calls[-2:] == [
        "agent.tool_call.evaluate_answer",
        "agent.tool_call.update_learning_state",
    ]


def test_summary_without_answers(seeded_db, tmp_path):
    sess, _ = _start(tmp_path)
    summary = sess.summary()
    assert summary["answered"] == 0
    assert summary["accuracy"] is None
    assert summary["session_row"]["words_covered"] == 0
