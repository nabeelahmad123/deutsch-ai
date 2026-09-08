"""Render eval scores to docs/AGENT_EVAL.md."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from backend.agent.eval.cases import CaseScore

_DOC = Path(__file__).resolve().parents[3] / "docs" / "AGENT_EVAL.md"
_TICK = {True: "y", False: "N"}


def _rate(scores: list[CaseScore], attr: str) -> str:
    n = sum(1 for s in scores if getattr(s, attr))
    return f"{n}/{len(scores)}"


def render(scores: list[CaseScore], *, model: str) -> str:
    passed = sum(1 for s in scores if s.passed)
    lines = [
        "# Agent evaluation",
        "",
        f"> `python -m backend.agent.eval` · model `{model}` · "
        f"{dt.date.today().isoformat()} · {len(scores)} cases",
        "",
        "The agent's **planning loop** is scored on three axes. Session sanity is "
        "checked against the database (due list, review history), not the model's "
        "claims. Cases and scoring: `backend/agent/eval/`.",
        "",
        "| axis | pass |",
        "|---|---|",
        f"| intent — minutes | {_rate(scores, 'intent_minutes_ok')} |",
        f"| intent — topic | {_rate(scores, 'intent_topic_ok')} |",
        f"| tool sequence | {_rate(scores, 'tools_ok')} |",
        f"| session sanity | {_rate(scores, 'session_ok')} |",
        f"| **overall** | **{passed}/{len(scores)}** |",
        "",
        "| case | request | minutes (want / got) | topic (want / got) | tools | session | pass |",
        "|---|---|---|---|:--:|:--:|:--:|",
    ]
    for s in scores:
        wm = "any" if s.expect_minutes is None else str(s.expect_minutes)
        wt = "—" if s.expect_topic is None else s.expect_topic
        lines.append(
            f"| `{s.id}` | {s.text} | {wm} / {s.got_minutes} | {wt} / {s.got_topic or '—'} "
            f"| {_TICK[s.tools_ok]} | {_TICK[s.session_ok]} | {_TICK[s.passed]} |"
        )

    fails = [s for s in scores if not s.passed]
    if fails:
        lines += ["", "## Failures", ""]
        for s in fails:
            lines.append(f"- **`{s.id}`** — {'; '.join(s.notes)}")
            lines.append(f"  - tool calls: `{s.tool_calls}`")
    else:
        lines += ["", "All cases passed."]

    lines += [
        "",
        "## Method",
        "",
        "- Each case runs the **real** agent (`run_session`) against a freshly "
        "seeded SQLite DB. No mocking of the LLM.",
        "- **intent** — parsed minutes within tolerance, topic exactly right "
        "(`null`/`general` both pass when no topic is implied).",
        "- **tool sequence** — `create_learning_session` exactly once, `create_quiz` "
        "after it, and never a grading tool inside the planning loop.",
        "- **session sanity** — composed from the DB, not the model's word: review "
        'words really are due, "new" words really are unseen, the lists are '
        "disjoint, and the count fits the time budget.",
        "",
        f"Run on `{model}` — the model the deployment uses (Haiku keeps the live "
        "demo cheap). To compare against a stronger model: "
        "`python -m backend.agent.eval --model claude-opus-5`.",
        "",
    ]
    return "\n".join(lines)


def write(scores: list[CaseScore], *, model: str) -> Path:
    _DOC.write_text(render(scores, model=model), encoding="utf-8")
    return _DOC
