"""Run the agent eval suite live and write docs/AGENT_EVAL.md.

DATABASE_URL is set to a throwaway SQLite file by the harness.
ANTHROPIC_API_KEY must be set (ANTHROPIC_MODEL, or --model, picks the model).

python -m backend.agent.eval
python -m backend.agent.eval --model claude-opus-5
"""

from __future__ import annotations

import argparse
import os

from backend.agent.eval.harness import run_suite
from backend.agent.eval.report import write
from backend.agent.orchestrator import DEFAULT_MODEL


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL)
    ap.add_argument("--no-write", action="store_true", help="print only, don't touch the doc")
    args = ap.parse_args()

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit("set ANTHROPIC_API_KEY to run the eval")

    scores = run_suite(model=args.model)
    passed = sum(1 for s in scores if s.passed)
    for s in scores:
        mark = "PASS" if s.passed else "FAIL"
        extra = "" if s.passed else f"  ({'; '.join(s.notes)})"
        print(f"  {mark}  {s.id:16} {s.tool_calls}{extra}")
    print(f"\n{passed}/{len(scores)} cases passed on {args.model}")

    if not args.no_write:
        path = write(scores, model=args.model)
        print(f"wrote {path}")
    raise SystemExit(0 if passed == len(scores) else 1)


if __name__ == "__main__":
    main()
