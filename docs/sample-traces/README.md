# Sample agent traces

Real traces from the agent, captured with
`python -m backend.agent.eval.capture` (model `claude-haiku-4-5`, a freshly
seeded DB). Regenerate any time. Each line is one `TraceEvent`
(`backend/tracing/tracer.py`): `{kind, name, input, output, latency_ms, success, ts}`.

| file | request | what it shows |
|---|---|---|
| [`plan-work-10min.jsonl`](plan-work-10min.jsonl) | "I have 10 minutes, German for work" | the happy path — 3 tool calls, session composed |
| [`plan-no-duration.jsonl`](plan-no-duration.jsonl) | "help me brush up before my trip to Berlin" | no duration given → agent defaults to 10 min; topic inferred as `travel` |
| [`converse-session-and-note.jsonl`](converse-session-and-note.jsonl) | "set up a 10-minute session and note my progress" | **cross-server** — learning tools then a notes-vault write, with an agent turn between them |

## Reading `converse-session-and-note.jsonl`

```
agent.turn                          turn 1: LLM asks for get_user_profile
learning.tool.get_user_profile      MCP server #1 answers (target=work, ceiling=A1)
agent.tool_call.get_user_profile    the same call, seen from the agent side
learning.tool.create_learning_session   server #1 composes + persists the session
agent.tool_call.create_learning_session
agent.turn                          turn 2: LLM now switches surfaces
notes.tool.log_progress             MCP server #2 (the vault) appends a dated section
agent.tool_call.log_progress
agent.turn                          turn 3: no tool calls -> final reply, loop ends
```

Two things this makes concrete:

- **Server boundary.** `learning.tool.*` and `notes.tool.*` are different
  processes; the `agent.turn` between them is the model deciding it's done with
  server #1 and moving to server #2 — the orchestration, not a hard-coded script.
- **Double logging is intentional.** Every call appears twice — `agent.tool_call.<x>`
  (agent side, with latency) and `<server>.tool.<x>` (server side) — so a broken
  call can be pinned to the loop or the server.
