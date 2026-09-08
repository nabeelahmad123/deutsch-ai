"""The eval scoring logic (score_case) -- pure, no network, no DB.

The live suite (run_suite / python -m backend.agent.eval) needs a key and is not
run in CI; this pins the scoring so a green suite means something.
"""

from __future__ import annotations

from backend.agent.eval import report
from backend.agent.eval.cases import CASES, EvalCase
from backend.agent.eval.harness import score_case

GOOD = dict(
    stopped="completed",
    intent={"minutes_available": 10, "topic": "work"},
    tool_calls=["get_user_profile", "create_learning_session", "create_quiz"],
    review_ids=set(),
    new_ids={101, 102, 103},
    due_ids=set(),
    seen_ids=set(),
)
CASE = EvalCase("t", "10 minutes, work", 10, "work")


def test_a_clean_run_passes_every_axis():
    s = score_case(CASE, **GOOD)
    assert s.passed
    assert (s.intent_minutes_ok, s.intent_topic_ok, s.tools_ok, s.session_ok) == (
        True,
        True,
        True,
        True,
    )


def test_wrong_topic_fails_intent_topic_only():
    s = score_case(CASE, **{**GOOD, "intent": {"minutes_available": 10, "topic": "travel"}})
    assert not s.intent_topic_ok and s.tools_ok and s.session_ok
    assert "expected 'work'" in "; ".join(s.notes)


def test_minutes_outside_tolerance_fails():
    s = score_case(CASE, **{**GOOD, "intent": {"minutes_available": 25, "topic": "work"}})
    assert not s.intent_minutes_ok


def test_open_ended_minutes_accepts_any_positive_int():
    case = EvalCase("t", "help me with German", None, None)
    s = score_case(case, **{**GOOD, "intent": {"minutes_available": 12, "topic": None}})
    assert s.intent_minutes_ok and s.intent_topic_ok
    bad = score_case(case, **{**GOOD, "intent": {"minutes_available": None, "topic": None}})
    assert not bad.intent_minutes_ok


def test_forbidden_tool_call_fails_tools():
    s = score_case(CASE, **{**GOOD, "tool_calls": [*GOOD["tool_calls"], "evaluate_answer"]})
    assert not s.tools_ok
    assert "forbidden" in "; ".join(s.notes)


def test_double_compose_fails_tools():
    calls = ["create_learning_session", "create_learning_session", "create_quiz"]
    s = score_case(CASE, **{**GOOD, "tool_calls": calls})
    assert not s.tools_ok


def test_phantom_review_words_fail_session():
    s = score_case(CASE, **{**GOOD, "review_ids": {5, 6}, "due_ids": set()})
    assert not s.session_ok
    assert "not actually due" in "; ".join(s.notes)


def test_new_word_already_seen_fails_session():
    s = score_case(CASE, **{**GOOD, "new_ids": {101}, "seen_ids": {101}})
    assert not s.session_ok


def test_empty_session_fails():
    s = score_case(CASE, **{**GOOD, "new_ids": set(), "review_ids": set()})
    assert not s.session_ok


def test_over_budget_word_count_fails():
    s = score_case(CASE, **{**GOOD, "new_ids": set(range(200, 260))})  # 60 words for 10 min
    assert not s.session_ok


def test_report_renders_table_and_failures():
    scores = [
        score_case(CASE, **GOOD),
        score_case(CASE, **{**GOOD, "intent": {"minutes_available": 10, "topic": "travel"}}),
    ]
    md = report.render(scores, model="claude-haiku-4-5")
    assert "# Agent evaluation" in md
    assert "**1/2**" in md
    assert "## Failures" in md and "`t`" in md


def test_case_bank_is_well_formed():
    assert len(CASES) >= 10
    assert len({c.id for c in CASES}) == len(CASES)
    for c in CASES:
        assert "create_learning_session" in c.must_call
        assert "evaluate_answer" in c.must_not_call
