"""Run the agent against a real request (needs ANTHROPIC_API_KEY + a seeded DB).

    DATABASE_URL=sqlite+pysqlite:///local.db python -m backend.db.seed
    DATABASE_URL=sqlite+pysqlite:///local.db \\
        python -m backend.agent "I have 10 minutes, German for work" --user-id 1
"""

from __future__ import annotations

import argparse
import json

from backend.agent.orchestrator import SessionRequest, run_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="natural-language study request")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    result = run_session(SessionRequest(raw_text=args.request, user_id=args.user_id))
    print(
        json.dumps(
            {
                "stopped": result.stopped,
                "turns": result.turns,
                "intent": result.intent,
                "tool_calls": result.tool_calls,
                "session_id": result.session_id,
                "review_words": [w["lemma"] for w in result.review_words],
                "new_words": [w["lemma"] for w in result.new_words],
                "reply": result.reply,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
