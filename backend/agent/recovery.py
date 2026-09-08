"""Recovery-behaviour harness + report.

Drives each fault kind through a real agent run (the LLM is scripted so this is
deterministic and needs no API key) and classifies how the agent responded:

    recovered           -- overcame the fault, produced the asked-for result
    clarified           -- asked the user for the missing information
    failed_gracefully   -- stopped with a clear message, no crash, partial or
                           no result
    crashed / hung      -- must never happen

Then computes a tool-call success rate and a recovery rate and writes
docs/FAILURE_RECOVERY.md.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from backend.agent.failure_injection import (
    FaultInjectingClient,
    FaultKind,
    FaultSpec,
    ambiguate,
)
from backend.agent.mcp_client import build_default_clients
from backend.agent.orchestrator import SessionRequest, run_conversation, run_session
from backend.agent.scripted_llm import FakeLLM, response, text_block, tool_use
from backend.tracing.tracer import Tracer

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "FAILURE_RECOVERY.md"
_HANG_SECONDS = 10.0
_SESSION_ARGS = {"user_id": 1, "minutes_available": 10, "topic": None}


@dataclass
class Scenario:
    name: str
    fault: str  # human description
    kind: str  # run_session | run_conversation
    specs: list[FaultSpec]
    request: str
    script: list  # FakeLLM responses
    expected: str  # expected disposition


@dataclass
class Outcome:
    scenario: str
    fault: str
    disposition: str
    agent_response: str
    tool_calls: int
    tool_calls_ok: int
    faults_injected: int
    seconds: float
    matched_expectation: bool


def scenarios() -> list[Scenario]:
    """The scripted recovery cases. Each FakeLLM script encodes one plausible
    recovery strategy."""
    ambiguous = ambiguate("I have 30 minutes for German, for work")  # -> vague
    return [
        Scenario(
            name="timeout, retried once",
            fault="create_learning_session times out on the 1st call",
            kind="run_session",
            specs=[
                FaultSpec(FaultKind.timeout, target_tool="create_learning_session", max_fires=1)
            ],
            request="10 minutes of German",
            script=[
                response(tool_use("create_learning_session", _SESSION_ARGS)),
                response(tool_use("create_learning_session", _SESSION_ARGS)),
                response(text_block("Composed after one retry."), stop_reason="end_turn"),
            ],
            expected="recovered",
        ),
        Scenario(
            name="timeout, persistent",
            fault="create_learning_session times out every call",
            kind="run_session",
            specs=[FaultSpec(FaultKind.timeout, target_tool="create_learning_session")],
            request="10 minutes of German",
            script=[
                response(tool_use("create_learning_session", _SESSION_ARGS)),
                response(tool_use("create_learning_session", _SESSION_ARGS)),
                response(
                    text_block(
                        "The scheduler isn't responding right now, so I couldn't build a "
                        "session. Please try again in a minute."
                    ),
                    stop_reason="end_turn",
                ),
            ],
            expected="failed_gracefully",
        ),
        Scenario(
            name="malformed response, retried",
            fault="get_user_profile returns junk on the 1st call",
            kind="run_session",
            specs=[
                FaultSpec(FaultKind.malformed_response, target_tool="get_user_profile", max_fires=1)
            ],
            request="quick German session",
            script=[
                response(tool_use("get_user_profile", {"user_id": 1})),
                response(tool_use("get_user_profile", {"user_id": 1})),
                response(tool_use("create_learning_session", _SESSION_ARGS)),
                response(
                    text_block("Profile re-fetched, session composed."), stop_reason="end_turn"
                ),
            ],
            expected="recovered",
        ),
        Scenario(
            name="malformed response, worked around",
            fault="get_user_profile returns junk every call",
            kind="run_session",
            specs=[FaultSpec(FaultKind.malformed_response, target_tool="get_user_profile")],
            request="quick German session",
            script=[
                response(tool_use("get_user_profile", {"user_id": 1})),
                response(
                    text_block("Profile data looks corrupt; proceeding with defaults."),
                    tool_use("create_learning_session", _SESSION_ARGS),
                ),
                response(
                    text_block("Session composed without the profile."), stop_reason="end_turn"
                ),
            ],
            expected="recovered",
        ),
        Scenario(
            name="ambiguous request, clarified",
            fault=f"request stripped of cues: {ambiguous!r}",
            kind="run_session",
            specs=[],
            request=ambiguous,
            script=[
                response(
                    text_block(
                        "How many minutes do you have, and any particular focus "
                        "(work, travel, exam)?"
                    ),
                    stop_reason="end_turn",
                ),
            ],
            expected="clarified",
        ),
        Scenario(
            name="ambiguous request, safe default",
            fault=f"request stripped of cues: {ambiguous!r}",
            kind="run_session",
            specs=[],
            request=ambiguous,
            script=[
                response(
                    text_block("No time given; assuming a 10-minute general session."),
                    tool_use("create_learning_session", _SESSION_ARGS),
                ),
                response(text_block("Here's a 10-minute session."), stop_reason="end_turn"),
            ],
            expected="recovered",
        ),
        Scenario(
            name="cross-server: notes down",
            fault="log_progress times out every call (server #2)",
            kind="run_conversation",
            specs=[FaultSpec(FaultKind.timeout, target_tool="log_progress")],
            request="Compose a 10-minute German session and note where I'm at",
            script=[
                response(tool_use("create_learning_session", {**_SESSION_ARGS, "topic": "work"})),
                response(
                    tool_use(
                        "log_progress", {"summary": "10-min work session", "date": "2026-09-03"}
                    )
                ),
                response(
                    tool_use(
                        "log_progress", {"summary": "10-min work session", "date": "2026-09-03"}
                    )
                ),
                response(
                    text_block(
                        "Your session is ready. I couldn't save a progress note -- the notes "
                        "service isn't responding."
                    ),
                    stop_reason="end_turn",
                ),
            ],
            expected="failed_gracefully",
        ),
    ]


_REPORTS_FAILURE = re.compile(
    r"could ?n[o']t|unable to|failed to|isn'?t responding|not responding|couldn't save",
    re.I,
)


def _classify(kind: str, result) -> str:
    reply = (getattr(result, "reply", "") or "").strip()
    composed = getattr(result, "session_id", None) is not None or (
        kind == "run_conversation" and "learning" in getattr(result, "servers_used", [])
    )
    stopped = getattr(result, "stopped", "")

    if stopped == "refusal":
        return "failed_gracefully"
    if "?" in reply and not composed:
        return "clarified"
    # An explicit "I couldn't ..." means the agent is reporting a shortfall, even
    # if the primary goal happened to succeed (partial success -> graceful).
    if _REPORTS_FAILURE.search(reply):
        return "failed_gracefully"
    if composed and stopped == "completed":
        return "recovered"
    if reply:
        return "failed_gracefully"
    return "failed_gracefully"


def run_scenario(scenario: Scenario, *, trace_dir: Path) -> Outcome:
    trace_path = trace_dir / f"{scenario.name.replace(' ', '_').replace(',', '')}.jsonl"
    tracer = Tracer(trace_path)
    mcp = FaultInjectingClient(build_default_clients(tracer=tracer), scenario.specs, tracer=tracer)
    request = SessionRequest(raw_text=scenario.request, user_id=1)

    started = time.perf_counter()
    disposition = "crashed"
    result = None
    try:
        if scenario.kind == "run_conversation":
            result = run_conversation(
                request, mcp_client=mcp, llm_client=FakeLLM(list(scenario.script)), tracer=tracer
            )
        else:
            result = run_session(
                request, mcp_client=mcp, llm_client=FakeLLM(list(scenario.script)), tracer=tracer
            )
    except Exception as exc:  # noqa: BLE001 - a crash is a valid (bad) outcome to record
        disposition = "crashed"
        agent_response = f"EXCEPTION: {type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started
        return Outcome(
            scenario.name,
            scenario.fault,
            disposition,
            agent_response,
            0,
            0,
            len(mcp.injected),
            elapsed,
            disposition == scenario.expected,
        )

    elapsed = time.perf_counter() - started
    events = (
        [json.loads(x) for x in trace_path.read_text().splitlines()] if trace_path.exists() else []
    )
    tool_events = [e for e in events if e["name"].startswith("agent.tool_call.")]
    ok = sum(1 for e in tool_events if e.get("success"))

    disposition = "hung" if elapsed > _HANG_SECONDS else _classify(scenario.kind, result)

    return Outcome(
        scenario=scenario.name,
        fault=scenario.fault,
        disposition=disposition,
        agent_response=(result.reply or "").strip()[:140],
        tool_calls=len(tool_events),
        tool_calls_ok=ok,
        faults_injected=len(mcp.injected),
        seconds=round(elapsed, 3),
        matched_expectation=disposition == scenario.expected,
    )


@dataclass
class Metrics:
    scenarios: int
    tool_calls: int
    tool_calls_ok: int
    tool_call_success_rate: float
    faults_injected: int
    recovered: int
    clarified: int
    failed_gracefully: int
    crashed: int
    hung: int
    recovery_rate: float  # (recovered + clarified) / disrupted
    graceful_handling_rate: float  # 1 - (crashed + hung) / disrupted
    expectations_met: int


def compute_metrics(outcomes: list[Outcome]) -> Metrics:
    n = len(outcomes)
    tc = sum(o.tool_calls for o in outcomes)
    tc_ok = sum(o.tool_calls_ok for o in outcomes)
    disrupted = [o for o in outcomes if o.faults_injected or "cues" in o.fault]
    d = len(disrupted) or 1
    by = {
        k: sum(1 for o in outcomes if o.disposition == k)
        for k in ("recovered", "clarified", "failed_gracefully", "crashed", "hung")
    }
    recovered_fully = sum(1 for o in disrupted if o.disposition in ("recovered", "clarified"))
    bad = sum(1 for o in disrupted if o.disposition in ("crashed", "hung"))
    return Metrics(
        scenarios=n,
        tool_calls=tc,
        tool_calls_ok=tc_ok,
        tool_call_success_rate=round(tc_ok / tc, 3) if tc else 1.0,
        faults_injected=sum(o.faults_injected for o in outcomes),
        recovered=by["recovered"],
        clarified=by["clarified"],
        failed_gracefully=by["failed_gracefully"],
        crashed=by["crashed"],
        hung=by["hung"],
        recovery_rate=round(recovered_fully / d, 3),
        graceful_handling_rate=round(1 - bad / d, 3),
        expectations_met=sum(1 for o in outcomes if o.matched_expectation),
    )


def render_report(metrics: Metrics, outcomes: list[Outcome]) -> str:
    lines = [
        "# Failure recovery",
        "",
        "> Generated by `python -m backend.agent.recovery` -- deterministic, scripted",
        "> LLM (no API key). Fault injection: `backend/agent/failure_injection.py`.",
        "",
        "## Summary",
        "",
        f"- Scenarios run: **{metrics.scenarios}**",
        f"- Faults injected: **{metrics.faults_injected}**",
        f"- Tool-call success rate: **{metrics.tool_call_success_rate:.0%}** "
        f"({metrics.tool_calls_ok}/{metrics.tool_calls} agent tool calls returned a usable result)",
        f"- Recovery rate (recovered or clarified): **{metrics.recovery_rate:.0%}**",
        f"- Graceful-handling rate (never crashed or hung): "
        f"**{metrics.graceful_handling_rate:.0%}**",
        f"- Dispositions: {metrics.recovered} recovered · {metrics.clarified} clarified · "
        f"{metrics.failed_gracefully} failed gracefully · {metrics.crashed} crashed · "
        f"{metrics.hung} hung",
        "",
        "## Per scenario",
        "",
        "| Scenario | Injected fault | Disposition | Faults | Tool calls (ok/total) "
        "| Agent response |",
        "|---|---|---|---|---|---|",
    ]
    for o in outcomes:
        lines.append(
            f"| {o.scenario} | {o.fault} | **{o.disposition}** | {o.faults_injected} | "
            f"{o.tool_calls_ok}/{o.tool_calls} | {o.agent_response or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_report(*, trace_dir: Path) -> tuple[Metrics, list[Outcome], str]:
    outcomes = [run_scenario(s, trace_dir=trace_dir) for s in scenarios()]
    metrics = compute_metrics(outcomes)
    return metrics, outcomes, render_report(metrics, outcomes)


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        metrics, outcomes, report = build_report(trace_dir=Path(tmp))
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nwrote {REPORT_PATH}")
    if metrics.graceful_handling_rate < 1.0:
        raise SystemExit("a scenario crashed or hung -- see the report")


if __name__ == "__main__":
    main()
