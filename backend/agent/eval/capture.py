"""Capture real agent traces for the docs.

    ANTHROPIC_API_KEY=... python -m backend.agent.eval.capture

Runs a handful of requests through the real agent and writes one JSONL trace
per request to docs/sample-traces/. Committed so a reader can see the tool-use
loop without running anything.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from backend.agent.orchestrator import SessionRequest, run_conversation, run_session
from backend.tracing.tracer import Tracer

OUT = Path(__file__).resolve().parents[3] / "docs" / "sample-traces"

REQUESTS = [
    ("plan-work-10min", "plan", "I have 10 minutes, German for work"),
    ("plan-no-duration", "plan", "help me brush up before my trip to Berlin"),
    ("converse-session-and-note", "converse", "set up a 10-minute session and note my progress"),
]


def _seed() -> None:
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tempfile.mkdtemp()}/traces.db"
    from backend.db import seed as db_seed
    from backend.db import session as db_session

    db_seed.upgrade_to_head()
    db_session.configure(os.environ["DATABASE_URL"], force=True)
    db_seed.seed_from_sql(db_seed.SEED_SQL)


def main() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit("set ANTHROPIC_API_KEY to capture traces")
    _seed()
    OUT.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("ANTHROPIC_MODEL")

    for slug, mode, text in REQUESTS:
        path = OUT / f"{slug}.jsonl"
        tracer = Tracer(path)
        req = SessionRequest(raw_text=text, user_id=1)
        if mode == "converse":
            res = run_conversation(req, tracer=tracer, model=model)
            print(f"{slug}: {res.stopped}, servers={res.servers_used}, {res.turns} turns")
        else:
            res = run_session(req, tracer=tracer, model=model)
            print(f"{slug}: {res.stopped}, tools={res.tool_calls}, {res.turns} turns")
        print(f"  -> {path.relative_to(OUT.parents[1])}")


if __name__ == "__main__":
    main()
