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

### Day 2 — `LG-02` Real frequency + Wiktionary ingestion  `[x]`
- [x] `ingest_frequency.build_from_raw()` + `extract_leipzig_words()` for the Leipzig
      `deu_news_2024_1M` tar.gz layout (`id\tword\tfreq`); token filter, case-fold,
      freq sort, top-N cut
- [x] ~4,000 frequency-ranked lemmas; OpenSubtitles cross-check (Spearman ρ = 0.512
      vs. Leipzig; stands in for SUBTLEX-DE which needs a manual download)
- [x] `ingest_wiktionary.build_from_kaikki()` — streams the kaikki.org German
      Wiktextract JSONL; derives article (gender), plural, `translation_en`, IPA;
      drops inflected-form pseudo-entries
- [x] `backend/data/README.md` with source + licensing table; `raw/` + `build/` gitignored
- [x] Parser unit tests (`backend/data/tests/`), added to pytest + CI
- **AC met:** `build/words.jsonl` = 3,899 enriched rows (of 4,000; 101 had no usable
  Wiktionary entry); two consecutive full runs produce byte-identical
  `frequency.jsonl` / `words.jsonl` / `seed.sql` (MD5 verified).
- **Deferred to `LG-03`:** loading `seed.sql` into live Postgres (Docker daemon
  not running in this env); `docker compose config` validates.

### Day 3 — `LG-03` Schema migrations + topic tagging + CRUD hardening  `[x]`
- [x] Alembic wired into `backend/db/migrations/` (`env.py`, `script.py.mako`,
      `0001_initial`); `sa.Enum` so it runs on SQLite too. `alembic check` = no drift.
- [x] `backend/db/seed.py`: `alembic upgrade head` + idempotent vocab load (from
      `build/words.jsonl`, or replay the committed `seed.sql`); `build_seed.py` is
      now DATA-only (schema owned by Alembic)
- [x] `assign_topic.py` — approximate gloss-keyword topic tagger, 14 topics;
      `seed.sql` regenerated: 3899 words, 378 topic-tagged, deterministic
- [x] CRUD hardening: `GET /words` now a `{total,limit,offset,items}` envelope with
      `cefr_level` / `topic` / `article` / `q` (lemma prefix) filters + validated
      pagination; new `GET /topics`; `422` on bad enum/params; `404` on
      review-logs for unknown user; `IntegrityError` handler
- [x] `docker-compose`: dropped the Postgres init-mount; `backend` now runs
      `alembic upgrade head && seed && uvicorn`. `Dockerfile` + `.dockerignore` fixed.
- [x] Tests: `backend/db/tests/` (migration up/down/no-drift, seeder idempotency,
      semicolon-safe SQL replay) + `test_assign_topic.py`; 53 pass, ruff/black clean
- **AC (partial):** `GET /words?cefr_level=A1&topic=…` works (covered by tests);
  migrate+seed verified end-to-end on SQLite. **`docker compose up` against live
  Postgres still unrun** — Docker daemon down in this env; `docker compose config`
  validates and the same commands passed on SQLite.

> **Build-order step 1 (sections 4–6) is now complete** bar the live-Postgres
> smoke test, which needs Docker running.

### Day 4 — `LG-04` SM-2 scheduler — state + updates  `[x]`
- [x] `sm2_update(state, quality)` — full SuperMemo-2 recurrence (EF floor 1.3,
      1/6/round(I·EF) intervals, reset on q<3); pure, no mutation
- [x] `quality_from_response(correct, latency)` — deterministic bool+ms → grade 0..5
- [x] `replay(logs)` / `get_card_state(session, …)` — state folded from `review_logs`
      (no card-state table; matches the section 5 data model)
- [x] `words_due_for_review(session, user_id, as_of)` — reconstruct per word,
      filter by due date, order most-overdue-first
- [x] `update_after_review(session, …, *, as_of=None)` — appends one `review_logs`
      row; `source` = `new` on first review else `review`; clamps negative latency
- [x] `Session` dataclass renamed `SessionPlan` (collided with the ORM model +
      SQLAlchemy `Session`)
- **AC met:** `backend/core/tests/test_sm2.py` (pure recurrence, EF floor,
  hand-checked reference sequence `[4,4,3,5]`→rep 4/I 35/EF 2.46) +
  `test_scheduler_db.py` (SQLite fixture, no network). 78 tests pass; **core
  coverage 97%**. `select_new_words` / `build_session` still stubbed → LG-05.

### Day 5 — `LG-05` SM-2 scheduler — selection + session + coverage  `[x]`
- [x] `cefr_ceiling(session, user_id)` — one band above the hardest band answered
      correctly (default A1, capped B2); a deterministic heuristic
- [x] `select_new_words(session, user_id, topic, n)` — unseen words within the
      ceiling, frequency-ordered, optional topic filter
- [x] `build_session(session, user_id, minutes, topic, *, as_of=None)` —
      `plan_budget` over due + available-new counts, then fill the slots;
      review/new lists disjoint by construction
- [x] Property tests: 300 seeded random grade sequences assert EF ≥ 1.3,
      reps ≥ 0, interval ≥ 1, reset on q<3, successful reviews never shorten the
      interval; monotonic-interval and reproducibility checks
- **AC met (DoD §17): `backend/core` at 100% coverage, zero LLM/network
  imports** (verified by AST scan). 392 tests pass.

> **Build-order step 2 (deterministic scheduler) is complete.** Next: `LG-06`,
> MCP server #1.

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
