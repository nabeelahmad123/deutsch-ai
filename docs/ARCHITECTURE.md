# Architecture

> Placeholder. Written once the system is stable (CLAUDE.md section 4), with a
> diagram + explanation. Below is the intended shape, for orientation only.

```
              natural language ("I have 10 minutes, German for work")
                                   │
                            ┌──────▼───────┐
                            │    agent     │  orchestrator.py
                            │ (Anthropic   │  - parses intent (only NL step)
                            │  tool use)   │  - never does scheduling math
                            └───┬─────┬────┘
                    MCP tools   │     │   MCP tools
                 ┌──────────────▼─┐ ┌─▼─────────────────┐
                 │ MCP server #1  │ │  MCP server #2    │  separate processes
                 │ learning tools │ │ notes / calendar  │
                 └──────┬─────────┘ └───────────────────┘
                        │ (only path to the data layer)
                 ┌──────▼───────────────────────┐
                 │ backend/core  (deterministic)│  SM-2, session budget
                 │  no LLM, no network but DB   │
                 └──────┬───────────────────────┘
                 ┌──────▼───────┐
                 │  PostgreSQL  │  words, users, review_logs, sessions
                 └──────────────┘

  every tool call + agent decision ──► backend/tracing/tracer.py (JSONL)
  learner_model/ (offline): simulator + HLR vs SM-2 vs random ──► docs/EVALUATION.md
```

## Non-negotiable principles (see CLAUDE.md section 2)

1. The scheduler is deterministic, zero LLM dependency, fully unit-testable.
2. The agent never computes scheduling decisions — it calls tools.
3. MCP tools are the only way the agent touches the data layer.
4. Every tool call and agent decision is traced from day one.
5. The two MCP servers are genuinely independent processes.
