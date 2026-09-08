"""Labelled requests for the agent eval.

``expect_minutes`` None means the request names no duration -- the agent may pick
one (we only check it's a sane positive int). ``expect_topic`` None means no
topic is implied (``general`` or null both pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_PLAN_TOOLS = ("create_learning_session", "create_quiz")
_NEVER_IN_PLAN = ("evaluate_answer", "update_learning_state", "finish_learning_session")


@dataclass(frozen=True)
class EvalCase:
    id: str
    text: str
    expect_minutes: int | None
    expect_topic: str | None
    minutes_tol: int = 0
    must_call: tuple[str, ...] = _PLAN_TOOLS
    must_not_call: tuple[str, ...] = _NEVER_IN_PLAN
    note: str = ""


CASES: list[EvalCase] = [
    EvalCase("explicit_work", "I have 10 minutes, German for work", 10, "work"),
    EvalCase("explicit_travel", "20 minutes please, travel vocabulary", 20, "travel"),
    EvalCase(
        "exam_prep",
        "I've got 15 minutes and an exam coming up",
        15,
        None,
        note="'exam' is a learner target, not a word topic -> no topic filter",
    ),
    EvalCase("minutes_only", "quick session, about 5 minutes", 5, None, minutes_tol=1),
    EvalCase("half_an_hour", "I've got half an hour to study German", 30, None, minutes_tol=2),
    EvalCase(
        "topic_only_trip",
        "help me brush up before my trip to Berlin",
        None,
        "travel",
        note="topic must be inferred from 'trip', no duration given",
    ),
    EvalCase(
        "topic_food",
        "10 minutes on food and cooking words",
        10,
        "food",
        note="free-form subject topic, not one of the targets",
    ),
    EvalCase(
        "vague",
        "help me with my German",
        None,
        None,
        note="no duration, no topic -- agent should still compose something sane",
    ),
    EvalCase("long_general", "45 minute session, general vocab", 45, None, minutes_tol=2),
    EvalCase(
        "work_wordy",
        "I'm on my commute, got maybe ten minutes, want to focus on office / work German",
        10,
        "work",
        minutes_tol=2,
    ),
    EvalCase(
        "tiny",
        "two minutes only",
        2,
        None,
        minutes_tol=1,
        note="edge: a budget almost too small for a session",
    ),
    EvalCase("travel_short", "5 min, holiday phrases", 5, "travel", minutes_tol=1),
]

# extra sanity: no duplicate ids
assert len({c.id for c in CASES}) == len(CASES)


@dataclass
class CaseScore:
    id: str
    text: str
    stopped: str
    expect_minutes: int | None
    expect_topic: str | None
    got_minutes: int | None
    got_topic: str | None
    tool_calls: list[str]
    intent_minutes_ok: bool
    intent_topic_ok: bool
    tools_ok: bool
    session_ok: bool
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all((self.intent_minutes_ok, self.intent_topic_ok, self.tools_ok, self.session_ok))
