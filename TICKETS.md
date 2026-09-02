# Tickets — day-by-day plan

~4 weeks / 20 working days, one engineer. Ordered per `CLAUDE.md` section 15;
each ticket closes against the Definition of Done in section 17. Do not start a
day with the previous day red.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Week 1 — Data pipeline + deterministic core

### Day 1 — `LG-01` Repo scaffold + data pipeline start  `[~]`
- [x] Section 4 repo tree, package stubs, `uv` project, ruff/black, CI
- [x] `docker-compose.yml` (real Postgres + stub services), `Dockerfile`, `.env.example`
- [x] `data/assign_cefr.py` + `data/build_seed.py`, starter `seed.sql`, FastAPI CRUD + tests
- [x] `core/session_budget.py` + tests, `tracing/tracer.py`
- **AC:** `uv run pytest`, `ruff`, `black --check` green; `docker compose config` valid.

### Day 2 — `LG-02` Real frequency + Wiktionary ingestion
- [ ] Implement `ingest_frequency.build_from_raw()` for the Leipzig archive layout
- [ ] Download + parse to ~4,000 frequency-ranked lemmas; SUBTLEX-DE cross-check
- [ ] Implement Wiktionary dump streamer in `ingest_wiktionary.py` (gender, plural, EN gloss)
- [ ] Licensing check documented in `data/README.md`; raw files stay gitignored
- **AC:** `build/words.jsonl` has ~4k enriched rows; re-running is deterministic.

### Day 3 — `LG-03` Schema migrations + topic tagging + CRUD hardening
- [ ] Wire Alembic into `backend/db/migrations/`; initial migration matches `models.py`
- [ ] `assign_cefr` applied across full list; add `topic` tagging (rule/keyword-based)
- [ ] Regenerate `seed.sql` from full dataset; load into Postgres via compose
- [ ] CRUD: pagination, filtering by cefr/topic, error cases; raise API test coverage
- **AC:** `docker compose up` seeds ~4k words; `GET /words?cefr_level=A1&topic=…` works.

### Day 4 — `LG-04` SM-2 scheduler — state + updates
- [ ] `CardState` reconstruction from `review_logs`; `sm2_update(state, quality)` recurrence
- [ ] `words_due_for_review(user_id, as_of)` against sqlite fixture DB
- [ ] `update_after_review(...)` writes a `review_logs` row + recomputes state
- **AC:** unit tests with in-memory DB, no network; deterministic given fixed inputs.

### Day 5 — `LG-05` SM-2 scheduler — selection + session + coverage
- [ ] `select_new_words(user_id, topic, n)` (frequency-ordered, unseen, CEFR-gated)
- [ ] `build_session(...)` = `plan_budget` + fill review/new slots
- [ ] Property tests (monotonic intervals, EF floor 1.3, no dup words in a session)
- **AC (DoD §17):** `backend/core` >90% coverage, zero LLM/network imports.

---

## Week 2 — MCP server #1 + agent

### Day 6 — `LG-06` MCP server #1 — profile + word tools
- [ ] Server process with official MCP Python SDK, own transport/port
- [ ] Tools: `get_user_profile`, `get_words_due_for_review`, `get_weak_words`, `get_new_words`
- [ ] Each tool wraps `backend/core` only — no direct DB access from tool bodies beyond core
- **AC:** tools callable from MCP inspector; inputs/outputs typed.

### Day 7 — `LG-07` MCP server #1 — quiz + grading + state
- [ ] `create_quiz(word_ids, quiz_type)`, `update_learning_state(user_id, word_id, correct)`
- [ ] `evaluate_answer` — exact/fuzzy match path + LLM semantic grading path for free text
- [ ] `create_learning_session(user_id, minutes_available, topic)` composes and returns a session
- **AC:** quiz round-trip works; free-text grading returns a score + rationale.

### Day 8 — `LG-08` MCP server #1 — resource + standalone sign-off
- [ ] Expose the vocab table as an MCP **resource** (not just tools)
- [ ] Full manual test session via MCP inspector / Claude Desktop; fix protocol bugs
- [ ] Trace every tool call (name, input, output, latency, success) via `tracer.py`
- **AC (DoD §17):** server responds correctly to a manual session, independent of agent code.

### Day 9 — `LG-09` Agent orchestrator — intent + loop
- [ ] `orchestrator.run_session` — parse intent (time budget, topic/target); the one NL step
- [ ] Anthropic API tool-use loop bound to MCP server #1 tools
- [ ] Every tool call + agent decision traced
- **AC:** "I have 10 minutes, German for work" → correct tool sequence in the trace.

### Day 10 — `LG-10` Agent — quiz + grade + update loop
- [ ] Generate/return quiz content; grade answers via `evaluate_answer` as they arrive
- [ ] `update_learning_state` after each answer; session summary at the end
- **AC (DoD §17):** one NL request → correctly-composed session, full trace logs.

---

## Week 3 — MCP server #2 + failure handling + simulator

### Day 11 — `LG-11` MCP server #2 (notes)
- [ ] Second server, genuinely separate process + transport (principle #5)
- [ ] Notes tools: write/append weekly progress summary to a markdown vault
- **AC:** server runs and is testable standalone via MCP inspector.

### Day 12 — `LG-12` Cross-server orchestration
- [ ] Agent wired to both MCP servers in one conversation
- [ ] Flow: "set up daily 10-minute sessions this week and remind me Monday"
- **AC (DoD §17):** one conversation uses both servers; trace shows reasoning between them.

### Day 13 — `LG-13` Failure injection
- [ ] `failure_injection.py`: timeout, malformed/unexpected MCP response, ambiguous request
- [ ] `wrap_tool(tool, spec)` injects faults per probability/target
- **AC:** each fault type reproducibly triggerable in a test.

### Day 14 — `LG-14` Recovery behavior + recovery-rate report
- [ ] Verify agent response per fault: retry / fallback / clarify / graceful fail — never hang/crash
- [ ] Compute + report tool-call success and recovery rate from traces
- **AC (first-class deliverable §11):** recovery-rate table produced from a scripted run.

### Day 15 — `LG-15` Learner simulator
- [ ] `simulator.py`: parameterised forgetting curves; learner types fast/average/forgetful
- [ ] Emits `(word_id, correct, response_time, elapsed_since_last_review)` logs; seeded RNG
- **AC:** fixed seed → identical logs; three learner types visibly differ in retention.

---

## Week 4 — Learned model, evaluation, frontend, ship

### Day 16 — `LG-16` Half-Life Regression model
- [ ] Feature extraction (lag, correct/incorrect history, word difficulty/frequency)
- [ ] `predict_half_life`, `predict_recall`, `fit` (Settles & Meeder 2016 objective)
- **AC:** trains on simulator logs; loss decreases; half-life clamped to bounds.

### Day 17 — `LG-17` Evaluation harness
- [ ] `evaluate.py`: random vs SM-2 vs HLR through the simulator
- [ ] Metrics: recall accuracy over time, Brier score, log-loss, AUC, review efficiency
- **AC:** single command produces a metrics dict for all three strategies.

### Day 18 — `LG-18` Evaluation writeup
- [ ] Generate plots for every metric; write `docs/EVALUATION.md` (real plots, no placeholders)
- [ ] Validate ≥1 metric against logged real sessions from the agent runs
- **AC (DoD §17):** `EVALUATION.md` complete with SM-2 vs HLR comparison + 1 real-data metric.

### Day 19 — `LG-19` Minimal frontend
- [ ] Run-a-session page (word/quiz → answer → feedback)
- [ ] Basic progress page (words learned, due count, retention)
- **AC:** both pages work against the live backend; ≤10% of project time spent here.

### Day 20 — `LG-20` Ship
- [ ] `docker compose up` brings up the whole system end to end
- [ ] CI green; `README.md` + `docs/ARCHITECTURE.md` diagram finalised, links to `EVALUATION.md`
- [ ] `NON_GOALS.md` current; tidy traces/config
- **AC (DoD §17):** full-system `compose up`, green CI, README explains architecture + links eval.

---

## Buffer / cut list (if behind)

Cut in this order (per section 16 non-goals + section 3 "if time allows"):
1. Contextual bandit for new-word selection (stretch only)
2. Langfuse / OpenTelemetry — keep JSON logging only
3. Topic tagging → single "general" topic
4. Frontend progress page → session page only
