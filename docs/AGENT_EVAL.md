# Agent evaluation

> `python -m backend.agent.eval` · model `claude-haiku-4-5-20251001` · 2026-09-08 · 12 cases

The agent's **planning loop** is scored on three axes. Session sanity is checked against the database (due list, review history), not the model's claims. Cases and scoring: `backend/agent/eval/`.

| axis | pass |
|---|---|
| intent — minutes | 12/12 |
| intent — topic | 11/12 |
| tool sequence | 12/12 |
| session sanity | 12/12 |
| **overall** | **11/12** |

| case | request | minutes (want / got) | topic (want / got) | tools | session | pass |
|---|---|---|---|:--:|:--:|:--:|
| `explicit_work` | I have 10 minutes, German for work | 10 / 10 | work / work | y | y | y |
| `explicit_travel` | 20 minutes please, travel vocabulary | 20 / 20 | travel / travel | y | y | y |
| `exam_prep` | I've got 15 minutes and an exam coming up | 15 / 15 | — / — | y | y | y |
| `minutes_only` | quick session, about 5 minutes | 5 / 5 | — / — | y | y | y |
| `half_an_hour` | I've got half an hour to study German | 30 / 30 | — / work | y | y | N |
| `topic_only_trip` | help me brush up before my trip to Berlin | any / 10 | travel / travel | y | y | y |
| `topic_food` | 10 minutes on food and cooking words | 10 / 10 | food / food | y | y | y |
| `vague` | help me with my German | any / 10 | — / — | y | y | y |
| `long_general` | 45 minute session, general vocab | 45 / 45 | — / — | y | y | y |
| `work_wordy` | I'm on my commute, got maybe ten minutes, want to focus on office / work German | 10 / 10 | work / work | y | y | y |
| `tiny` | two minutes only | 2 / 2 | — / — | y | y | y |
| `travel_short` | 5 min, holiday phrases | 5 / 5 | travel / travel | y | y | y |

## Failures

- **`half_an_hour`** — invented topic 'work'
  - tool calls: `['get_user_profile', 'create_learning_session', 'create_quiz']`
  - Known limitation: on a bare "study German" request with no subject, Haiku
    sometimes still guesses `work`. It composes a valid session either way; the
    only effect is the new words are work-flavoured. A stronger model or a
    firmer prompt closes this.

## Method

- Each case runs the **real** agent (`run_session`) against a freshly seeded SQLite DB. No mocking of the LLM.
- **intent** — parsed minutes within tolerance, topic exactly right (`null`/`general` both pass when no topic is implied).
- **tool sequence** — `create_learning_session` exactly once, `create_quiz` after it, and never a grading tool inside the planning loop.
- **session sanity** — composed from the DB, not the model's word: review words really are due, "new" words really are unseen, the lists are disjoint, and the count fits the time budget.

Run on `claude-haiku-4-5-20251001` — the model the deployment uses (Haiku keeps the live demo cheap). To compare against a stronger model: `python -m backend.agent.eval --model claude-opus-5`.
