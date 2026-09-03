# learn-german

An adaptive German-vocabulary learning system, built as a production-shaped demo
of **agentic AI / MCP orchestration** backed by **modest but real ML rigor**. It
is deliberately *not* a polished consumer app — the priorities are architectural
cleanliness, testability, and a genuine evaluation. See [`CLAUDE.md`](CLAUDE.md)
for the full brief and [`docs/NON_GOALS.md`](docs/NON_GOALS.md) for what it is
deliberately *not*.

## What it does

Ask in natural language — *"I have 10 minutes, I'm learning German for work"* —
and an **agent** composes a study session by calling **MCP tools**. The tools
wrap a **deterministic spaced-repetition scheduler**; the agent never does the
scheduling maths itself. A **second, independent MCP server** (a Markdown notes
vault) is wired into the same agent, so one conversation can span two unrelated
tool surfaces. The whole thing is **traced**, **fault-injected**, and
**evaluated** offline against real metrics.

## Architecture

```
  "I have 10 minutes, German for work"
                │
        ┌───────▼────────┐   backend/agent/orchestrator.py
        │     agent       │   • parses intent  (the ONLY natural-language step)
        │  Anthropic API  │   • never computes a schedule — it calls tools
        │   tool-use loop │   • every LLM turn + tool call traced
        └───┬────────┬────┘
   MCP tools│        │MCP tools          (backend/agent/mcp_client.py:
       ┌────▼──┐  ┌──▼──────┐             one client per server, unioned)
       │ MCP # 1│  │ MCP # 2 │  ← genuinely separate processes / transports
       │learning│  │  notes  │
       └────┬───┘  └────┬────┘
   only path│           │ filesystem
    to data │       ┌───▼────────┐  _vault/*.md   (progress.md weekly summary)
       ┌────▼─────────────────┐
       │ backend/core         │  deterministic: SM-2 + time-budget + selection
       │  scheduler.py        │  no LLM, no network but the DB, 100% covered
       │  read_models.py      │
       └────┬─────────────────┘
       ┌────▼─────┐   backend/api/  (thin: CRUD + human study endpoints)
       │PostgreSQL│   words · users · review_logs · sessions   (Alembic)
       └──────────┘

  every tool call + agent decision  ──►  backend/tracing/tracer.py  (JSONL)
  backend/learner_model/  (offline):  simulator → SM-2 vs HLR vs random
                                      → docs/EVALUATION.md  (real plots)
```

Details and the five non-negotiable principles: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| area | package | notes |
|---|---|---|
| deterministic core | `backend/core/` | SM-2, session budgeting, new-word selection, read projections. **Zero LLM/HTTP imports** (AST-asserted); 100% test coverage. |
| data pipeline | `backend/data/` | Leipzig frequency + Wiktextract enrichment → ~2,560 A1–B2 study words (~1,340 function words and inflected/grammatical entries filtered out). `seed.sql` committed; raw corpora gitignored. |
| schema | `backend/db/` | SQLAlchemy models + Alembic migrations; `seed.py` migrate-and-load. |
| quiz + grading | `backend/study/` | quiz construction; exact/fuzzy grading, with an LLM semantic path for free-text. Shared by the MCP server and the API. |
| MCP server #1 | `backend/mcp_servers/learning_server/` | 9 tools + a `vocab://` resource; own process, own transport. |
| MCP server #2 | `backend/mcp_servers/secondary_server/` | a Markdown notes vault. Own process, own storage — imports nothing from server #1 (AST-asserted). |
| agent | `backend/agent/` | intent → tool loop → session + quiz; cross-server conversations; fault injection + a recovery-rate report. |
| tracing | `backend/tracing/` | JSONL: name, input, output, latency, success — from day one. |
| learner model | `backend/learner_model/` | forgetting-curve simulator, Half-Life Regression, the SM-2-vs-HLR evaluation. |
| API | `backend/api/` | thin FastAPI: CRUD + `/study/*` endpoints for the frontend. |
| frontend | `frontend/` | static, no build: a vocabulary browser + a run-a-session / progress page. |

## Quick start — Docker

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY (only the agent needs it)
docker compose up             # Postgres + backend (migrates + seeds) + both
                              # MCP servers + the static frontend
```

- API + Swagger: <http://localhost:8000/docs>
- Frontend: <http://localhost:5173/> (vocab browser) and `/study.html`
- MCP server #1: `http://localhost:8100/mcp` · server #2: `http://localhost:8101/mcp`

## Quick start — local (no Docker)

```bash
uv sync --extra dev --extra agent          # Python 3.12 project env
uv run pytest                              # 554 tests

# a local SQLite DB instead of Postgres:
export DATABASE_URL="sqlite+pysqlite:///local.db"
uv run python -m backend.db.seed           # migrate + load the seed

# the study API + static frontend:
uv run uvicorn backend.api.main:app --port 8000 &
(cd frontend && python -m http.server 5173)
open "http://localhost:5173/study.html?api=http://localhost:8000"

# the agent (needs ANTHROPIC_API_KEY), stdio MCP by default:
uv run python -m backend.agent "I have 10 minutes, German for work" --auto
uv run python -m backend.agent --converse \
    "Give me a 10-minute German work session and note where I'm at"

# regenerate the deliverables:
uv run python -m backend.learner_model.report   # docs/EVALUATION.md + plots
uv run python -m backend.agent.recovery         # docs/FAILURE_RECOVERY.md
```

## Evaluation

[`docs/EVALUATION.md`](docs/EVALUATION.md) — random vs SM-2 vs HLR through the
learner simulator, with real plots:

| strategy | recall (retention) | review efficiency | Brier | AUC |
|---|---|---|---|---|
| random | 0.04 | 0.005 | 0.25 | 0.50 |
| sm2 | 0.49 | 0.022 | 0.09 | 0.90 |
| hlr | 0.92 | 0.013 | 0.12 | 0.84 |

HLR maximises retention; SM-2 is the most review-efficient and best-calibrated.
The offline SM-2 recall (0.489) is **validated against a real `review_logs`
table** driven by the actual scheduler (0.481; Δ = 0.008).

[`docs/FAILURE_RECOVERY.md`](docs/FAILURE_RECOVERY.md) — deliberate timeout /
malformed-response / ambiguous-request faults through real agent runs:
**tool-call success 62%, recovery 71%, graceful-handling 100%** (never crashes or
hangs).

## Tests & CI

`.github/workflows/ci.yml` runs two jobs on every push:

- **core** — installs the minimal dependency set (no `mcp` / `anthropic`), runs
  `backend/core`, `backend/data`, `backend/db`, `backend/learner_model`,
  `backend/study` with `--cov-fail-under=90` on `backend.core`, plus ruff +
  black. `test_import_purity.py` asserts the core imports nothing LLM/HTTP.
- **full** — installs everything, runs the whole suite (554 tests).

## Build order

All 8 steps of `CLAUDE.md` section 15 are complete — see [`TICKETS.md`](TICKETS.md)
for the day-by-day log (`LG-01` … `LG-20`).
