# learn-german

Adaptive German vocabulary learning system — a production-shaped demo of agentic
AI / MCP orchestration backed by modest ML rigor. **Not** a polished consumer app;
see [`CLAUDE.md`](CLAUDE.md) for the full brief and [`docs/NON_GOALS.md`](docs/NON_GOALS.md).

> This README is a stub. It is rewritten last (build-order step 8) to point at the
> architecture diagram and real evaluation results.

## Shape

- **Deterministic scheduler** (`backend/core/`) — SM-2 + time-budget logic. No LLM,
  no network except the DB. Fully unit-tested.
- **Agent** (`backend/agent/`) — Anthropic tool-use loop. Turns "I have 10 minutes,
  German for work" into a composed session by calling MCP tools. Never does the
  scheduling math itself.
- **Two independent MCP servers** (`backend/mcp_servers/`) — learning tools, and a
  second surface (notes/calendar). Separate processes.
- **Evaluation** (`backend/learner_model/`) — learner simulator + SM-2 vs. HLR vs.
  random baseline, with calibration/retention/efficiency metrics.
- **Failure injection + tracing** — deliberate faults, measured recovery.

## Quick start

```bash
cp .env.example .env            # fill in ANTHROPIC_API_KEY etc.
uv sync --extra dev             # Python 3.12 project env
uv run pytest                   # core + learner_model + data + db + api

# Data pipeline (build-order step 1). --sample needs no downloads; the real run
# reads corpora from backend/data/raw/ (see backend/data/README.md):
uv run python -m backend.data.ingest_frequency  --sample
uv run python -m backend.data.ingest_wiktionary --sample
uv run python -m backend.data.build_seed        # regenerates backend/data/seed.sql (data only)

# Schema is Alembic; seeding is a separate idempotent step:
uv run alembic upgrade head
uv run python -m backend.db.seed --skip-migrate

# Full skeleton (Postgres real + migrated + seeded; other services are stubs):
docker compose up
```

## Build order

Tracked in `CLAUDE.md` section 15 and `TICKETS.md`. Next: **step 5 — MCP server
#2 + cross-server orchestration**.

| # | Step | State |
|---|------|-------|
| 1 | Data pipeline + schema + FastAPI CRUD | done (bar live-PG smoke test) |
| 2 | Deterministic scheduler, fully unit tested | done — SM-2, 100% core coverage |
| 3 | MCP server #1, tested standalone | done — 8 tools + vocab resources + traced |
| 4 | Agent + session flow (server #1) | done — compose → quiz → grade each answer → summary |
| 4 | Agent + session flow (server #1) | scaffolded |
| 5 | MCP server #2 + cross-server orchestration | done — one conversation spans learning + notes servers |
| 6 | Failure injection + tracing + recovery rate | done — see docs/FAILURE_RECOVERY.md |
| 7 | Learner simulator + HLR vs SM-2 eval + plots | simulator + HLR + eval done; plots = LG-18 |
| 8 | Minimal frontend + Docker/CI + README | Docker/CI done |
