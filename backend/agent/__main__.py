"""Run the agent against a real request (needs ANTHROPIC_API_KEY + a seeded DB).

    DATABASE_URL=sqlite+pysqlite:///local.db python -m backend.db.seed
    DATABASE_URL=sqlite+pysqlite:///local.db \\
        python -m backend.agent "I have 10 minutes, German for work" --user-id 1

--auto answers every question wrong to show the grade -> update_learning_state ->
summary flow. --converse runs the cross-server loop instead (learning + notes):

    python -m backend.agent --converse \\
        "Give me a 10-minute German work session and note where I'm at"
"""

from __future__ import annotations

import argparse
import json

from backend.agent.orchestrator import SessionRequest, run_conversation, start_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="natural-language study request")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument(
        "--auto", action="store_true", help="auto-answer every question wrong, then summarise"
    )
    parser.add_argument(
        "--converse", action="store_true", help="cross-server loop (learning + notes)"
    )
    args = parser.parse_args()

    if args.converse:
        conv = run_conversation(SessionRequest(raw_text=args.request, user_id=args.user_id))
        print(
            json.dumps(
                {
                    "stopped": conv.stopped,
                    "turns": conv.turns,
                    "servers_used": conv.servers_used,
                    "tool_calls": conv.tool_calls,
                    "reply": conv.reply,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    session = start_session(SessionRequest(raw_text=args.request, user_id=args.user_id))
    result = session.result

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
                "quiz": [{"prompt": q["prompt"], "hint": q["hint"]} for q in session.quiz],
                "reply": result.reply,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if args.auto:
        for question in session.quiz:
            fb = session.answer(question["question_id"], "(no answer)")
            print(
                f"  {question['prompt']}  ->  {fb.correct} ({fb.method}); expected {fb.expected!r}"
            )
        print(json.dumps(session.summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
