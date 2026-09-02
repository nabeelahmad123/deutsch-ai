# Project brief: adaptive German vocabulary learning system (agentic / MCP)

This file is the source of truth for this project. Read it fully before writing any code.
If anything here is ambiguous or you need to make a judgment call, state the assumption in
a comment or commit message and proceed — don't stall waiting for clarification unless it's
truly blocking (e.g. a missing credential).

## 1. What this project is

An end-to-end, production-shaped system for learning German vocabulary, where:

- A **deterministic scheduler** (not an LLM) decides which words a learner should review or
  learn next, based on a spaced-repetition / learner-recall model.
- An **agent**, exposed through **MCP tools**, turns natural-language requests
  ("I have 10 minutes, work German") into a composed learning session by calling those
  deterministic tools — it does not do the scheduling math itself.
- A **second, independent MCP server** (calendar or notes) is wired into the same agent, so
  the agent has to orchestrate across two unrelated tool surfaces, not just one.
- The system is **evaluated**, not just demoed: a learner simulator and an offline comparison
  between a classical baseline (SM-2) and a learned model (Half-Life Regression) produce real
  metrics (calibration, retention, review efficiency).
- **Failure handling is a deliberate feature**: timeouts, malformed tool responses, and
  ambiguous requests are injected and the agent's recovery behavior is traced and measured.

The purpose of this project is to demonstrate agentic AI / MCP orchestration engineering
skill, backed by genuine (if modest) ML rigor — NOT to be a polished consumer app. Prioritize
architectural cleanliness, testability, and a real evaluation over UI polish or feature count.

## 2. Non-negotiable architecture principles

These are constraints, not suggestions. Do not violate them for convenience.

1. **The scheduler is deterministic and has zero LLM dependency.** It must be fully unit-testable
   with no network calls, no API keys, no non-determinism. Given the same inputs it always
   returns the same outputs.
2. **The agent never computes scheduling decisions itself.** It calls tools that wrap the
   deterministic core. If you find yourself asking the LLM "which word should be reviewed
   next," stop — that's a bug in the design, not a prompt to improve.
3. **MCP tools are the only way the agent touches the data layer.** No direct DB access from
   agent/LLM code paths — everything goes through typed MCP tool calls, even in-process.
4. **Every tool call and agent decision is logged/traced** (tool name, input, output, latency,
   success/failure) from day one, not bolted on later.
5. **The two MCP servers are genuinely independent processes/services**, not two modules
   imported into one app pretending to be separate servers. This is the point of step 5 below.

## 3. Tech stack

- Backend: Python 3.12, FastAPI, PostgreSQL (SQLAlchemy or SQLModel), Pydantic for schemas
- MCP: official Anthropic MCP Python SDK for both servers
- Agent orchestration: Anthropic API with tool use (start here; do not reach for LangGraph/
  CrewAI/AutoGen unless a genuine multi-agent coordination need appears — see non-goals)
- Learner model: NumPy/PyTorch for Half-Life Regression, plain Python for SM-2 baseline
- Tracing: structured JSON logging to start; Langfuse or OpenTelemetry if time allows
- Frontend: minimal React or plain HTML/JS — this is explicitly low priority, see non-goals
- Infra: Docker + docker-compose, GitHub Actions for CI, pytest for tests
- Package management: pip with `--break-system-packages` inside the container is fine for
  throwaway scripts; use a proper venv/poetry/uv for the real backend package

## 4. Repository structure

```
.
├── CLAUDE.md                      # this file
├── docker-compose.yml
├── README.md                      # written last, points to eval plots + architecture diagram
├── backend/
│   ├── core/                      # deterministic scheduler — NO llm imports allowed here
│   │   ├── scheduler.py           # SM-2 baseline
│   │   ├── session_budget.py      # time-budget -> word count logic
│   │   └── tests/
│   ├── learner_model/             # HLR model, learner simulator, evaluation harness
│   │   ├── hlr.py
│   │   ├── simulator.py
│   │   ├── evaluate.py            # produces the comparison plots/metrics
│   │   └── tests/
│   ├── data/                      # ingestion scripts + seed data
│   │   ├── ingest_frequency.py    # Leipzig / SUBTLEX-DE
│   │   ├── ingest_wiktionary.py   # gender, plural, definitions
│   │   ├── assign_cefr.py         # frequency-band -> approximate CEFR tag
│   │   └── seed.sql
│   ├── db/
│   │   ├── models.py
│   │   └── migrations/
│   ├── api/                       # FastAPI app — thin, calls core/ and mcp/ only
│   │   └── main.py
│   ├── mcp_servers/
│   │   ├── learning_server/       # MCP server #1 — see section 8
│   │   └── secondary_server/      # MCP server #2 — see section 10 (calendar or notes)
│   ├── agent/
│   │   ├── orchestrator.py        # the tool-calling loop
│   │   └── failure_injection.py   # deliberate fault injection for testing, see section 11
│   └── tracing/
│       └── tracer.py
├── frontend/                      # minimal, built last
├── docs/
│   ├── ARCHITECTURE.md            # diagram + explanation, written once system is stable
│   ├── EVALUATION.md              # metrics + plots, written after learner_model/evaluate.py runs
│   └── NON_GOALS.md               # copy of section 13 below, for future contributors
└── .github/workflows/ci.yml
```

## 5. Data model (initial sketch — refine as needed, but keep it this simple)

```
words(id, lemma, article, plural, translation_en, cefr_level, frequency_rank, topic, ipa_or_audio_ref)
users(id, created_at, target)                         -- target: work / travel / general / exam
review_logs(id, user_id, word_id, timestamp, correct, response_time_ms, source: "review"|"new")
sessions(id, user_id, started_at, duration_minutes_requested, words_covered, topic)
```

## 6. Data scope

- **Levels: A1 through B2 only.** Do not attempt C1/C2 — sourcing and CEFR-tagging quality
  degrades badly there and it adds no engineering value to this project.
- **~4,000 frequency-ranked words**, tagged with an approximate CEFR level derived from
  frequency band (top ~500 ≈ A1, next ~1000 ≈ A2, etc.) — this is an approximation, document
  it as such, don't pretend it's authoritative.
- Sources: Leipzig Corpora Collection / Deutscher Wortschatz for frequency; SUBTLEX-DE as a
  cross-check; Wiktionary German dumps for gender/plural/definitions. Check licensing before
  redistributing any list verbatim — regenerate/derive rather than copy wholesale where the
  license is unclear.
- Pronunciation: do not source an audio dataset. Generate on demand via a TTS API, or store
  an IPA transcription only if audio generation is out of scope for time.

## 7. Deterministic core — contract

`backend/core/scheduler.py` must expose (signatures illustrative, adapt as needed):

```python
def words_due_for_review(user_id, as_of: datetime) -> list[WordId]: ...
def update_after_review(user_id, word_id, correct: bool, response_time_ms: int) -> None: ...
def select_new_words(user_id, topic: str | None, n: int) -> list[WordId]: ...
def build_session(user_id, minutes_available: int, topic: str | None) -> Session: ...
```

No LLM calls, no network calls except the DB, in this file or anything it imports. Unit test
with an in-memory/sqlite fixture DB so tests run in CI without a live Postgres.

## 8. MCP server #1 — learning tools

Build with the official MCP Python SDK. Expose as tools (not raw REST):

- `get_user_profile(user_id)`
- `get_words_due_for_review(user_id)`
- `get_weak_words(user_id, limit)`
- `get_new_words(user_id, topic, count)`
- `create_quiz(word_ids, quiz_type)`
- `evaluate_answer(question_id, user_answer)` — for free-text answers this calls the LLM
  internally for semantic grading; for others it's exact/fuzzy match
- `update_learning_state(user_id, word_id, correct)`
- `create_learning_session(user_id, minutes_available, topic)` — composes and returns a session

Also expose the vocab table itself as an MCP **resource**, not just tools — this is part of
the point of using MCP rather than a plain function-calling setup.

Test this server standalone (e.g. via Claude Desktop or the MCP inspector) before building
the agent that depends on it. Do not skip this — protocol-level bugs are much easier to find
in isolation than through an agent's indirection.

## 9. Agent

`backend/agent/orchestrator.py`: a tool-calling loop against the Anthropic API. Given a
request like "I have 10 minutes, I'm learning German for work," it should:

1. Parse intent (time budget, topic/target) — this is the one place natural-language
   reasoning is appropriate.
2. Call MCP server #1 tools to get due words, weak words, and candidate new words.
3. Call `create_learning_session`.
4. Generate/return quiz content, grade answers as they come in via `evaluate_answer`.
5. Call `update_learning_state` after each answer.

Log every tool call (name, args, result, latency, success/failure) via `tracing/tracer.py`.

## 10. MCP server #2 — second tool surface

Pick one: a calendar server (schedule recurring study sessions) or a notes server (export a
weekly progress summary, e.g. to a markdown file or Obsidian-style vault). It must be a
genuinely separate process/service from server #1, reachable over its own transport. The
agent should be able to use both in a single conversation (e.g. "set up daily 10-minute
sessions this week and remind me on Monday") — this is what actually demonstrates
orchestration across independent tool surfaces, which is the main point of this project.

## 11. Failure injection and tracing

`backend/agent/failure_injection.py` should be able to deliberately:

- Time out a tool call
- Return a malformed/unexpected MCP response
- Simulate an ambiguous user request

For each, verify and log how the agent responds (retry, fallback, ask for clarification, or
fail gracefully with a clear error — never silently hang or crash). Compute and report a
tool-call success/recovery rate as part of the final writeup. This is a first-class deliverable,
not an edge case to handle "if time allows."

## 12. Learner model and evaluation harness

`backend/learner_model/`:

- `simulator.py`: synthetic learners with parameterized forgetting curves (vary
  memory-decay rate, noise, and "learner type" — fast, average, forgetful) that produce
  plausible (word_id, correct, response_time, elapsed_since_last_review) interaction logs.
- `hlr.py`: Half-Life Regression model (Settles & Meeder, 2016, is the reference to
  implement against) — predicts memory half-life from features (lag time, history of
  correct/incorrect, word difficulty/frequency).
- `evaluate.py`: runs SM-2 baseline vs. HLR vs. a naive/random baseline through the
  simulator and produces:
  - Recall accuracy over simulated time
  - Calibration of predicted vs. actual recall probability (Brier score, log-loss, AUC)
  - Review efficiency (words retained per review issued)
  - Plots for all of the above, saved to `docs/EVALUATION.md`

Do NOT attempt Deep Knowledge Tracing or full reinforcement learning here — there isn't
enough real interaction data to make either meaningful, and it would be complexity without
signal. If a contextual bandit for new-word selection fits in the timeline, add it as a
stretch goal after everything above is solid — not before.

## 13. Frontend

Minimal. A page to run a session (show a word/quiz, take an answer, show feedback) and a
page to view basic progress. No auth system, no gamification, no mobile app. This is explicitly
low priority — do not spend more than ~10% of total project time here.

## 14. Environment and deployment

- `docker-compose.yml` bringing up: Postgres, the FastAPI backend, both MCP servers, and the
  frontend, in one command.
- `.env.example` listing every required variable (DB connection, Anthropic API key, any TTS
  API key) — never commit real secrets.
- GitHub Actions CI: run `pytest` on `backend/core` and `backend/learner_model` (the parts
  with no external dependencies) on every push; lint with ruff/black.

## 15. Build order (target: ~4 weeks, compress further if needed by cutting section 16 items)

Work through these in order. Each should be a working, tested increment — don't move to the
next step with a broken previous one.

1. Data pipeline + Postgres schema + FastAPI CRUD (section 4-6)
2. Deterministic scheduler, fully unit tested (section 7)
3. MCP server #1, tested standalone against an MCP client before anything depends on it (section 8)
4. Agent + session flow using MCP server #1 (section 9)
5. MCP server #2 + agent orchestration across both servers (section 10)
6. Failure injection + tracing + recovery-rate reporting (section 11)
7. Learner simulator + HLR vs. SM-2 evaluation with plots (section 12)
8. Minimal frontend + Docker/CI + README with architecture diagram and evaluation results (section 13-14)

## 16. Explicit non-goals — do not build these

- Full CEFR range (C1/C2)
- Multi-agent frameworks (LangGraph/CrewAI/AutoGen) unless a genuine coordination need
  appears after step 5 is done — a single well-scoped agent is correct for this project's
  actual complexity
- Reinforcement learning for scheduling/curriculum
- Deep Knowledge Tracing or any deep-learning knowledge-tracing model
- Your own speech-to-text or pronunciation-scoring model
- Fine-tuning any LLM
- Gamification, social features, leaderboards
- A native mobile app
- Building your own vocabulary/translation corpus from scratch

If you find yourself about to build one of these, stop and flag it rather than proceeding.

## 17. Definition of done (per phase, roughly)

- **Core is done** when `backend/core` has >90% test coverage and zero LLM/network imports.
- **MCP server #1 is done** when it responds correctly to a manual test session via an MCP
  client, independent of the agent code.
- **Agent orchestration is done** when a single natural-language request produces a
  correctly-composed session using tools from server #1, with full trace logs.
- **Multi-server orchestration is done** when one conversation demonstrably uses tools from
  both MCP servers and the trace shows the reasoning between them.
- **Evaluation is done** when `docs/EVALUATION.md` contains real plots (not placeholders)
  comparing SM-2 vs. HLR on the simulator, plus at least one metric validated against your
  own logged real sessions.
- **Project is done** when `docker-compose up` brings up a working system end to end, CI is
  green, and the README explains the architecture and links the evaluation results.

## 18. Day-1 instructions for Claude Code

1. Initialize the repo structure from section 4 (empty files/dirs are fine to start).
2. Set up `docker-compose.yml` with a Postgres service and stub services for backend/frontend
   (they can fail health checks initially — just get the skeleton running).
3. Set up the Python project (venv or uv), pytest, ruff/black, and a GitHub Actions CI
   workflow that runs `pytest` on `backend/core` (which won't exist yet — that's fine, make
   the CI job pass on an empty test suite for now).
4. Write `.env.example`.
5. Start on build-order step 1 (section 15): data ingestion scripts and the Postgres schema.
6. Commit early and often, with messages that reference which build-order step is in progress.

Do not skip ahead to the agent or MCP layers before the deterministic core (steps 1-2) is
solid and tested — that ordering is deliberate, not arbitrary.
