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

### Day 6 — `LG-06` MCP server #1 — profile + word tools  `[x]`
- [x] `MCPServer` (official SDK, `mcp` 2.1) in `learning_server/server.py`;
      `__main__` runs stdio by default, `streamable-http` on `LEARNING_MCP_*`
      (verified: HTTP server binds :8100, answers `initialize`)
- [x] Tools: `get_user_profile`, `get_words_due_for_review`, `get_weak_words`,
      `get_new_words` — typed via frozen dataclasses (`WordView`, `UserProfile`),
      so each tool publishes a real JSON output schema
- [x] Tool bodies call only `backend.core` — new `core/read_models.py` does
      hydration + the profile projection; `scheduler.weak_words` added. No ad-hoc
      DB queries in tool code.
- [x] Unknown user → `ToolError` (clean error result over the wire); limits clamped
- [x] tz fix: `scheduler` now normalises `review_logs.timestamp` to aware-UTC
      (SQLite hands back naive) so due-date maths never mixes naive/aware
- **AC met:** `backend/mcp_servers/tests/` drives all four tools in-process via
  `server.call_tool` (manifest, schemas, shapes, error path, clamping). 407 tests
  pass; core still 100%. Standalone MCP-client / Inspector session is LG-08.

> Stack note: `mcp` resolved to 2.1 (FastMCP→MCPServer rename); API is otherwise
> the same. Pinned `mcp>=2.1,<3`.

### Day 7 — `LG-07` MCP server #1 — quiz + grading + state  `[x]`
- [x] `create_quiz(word_ids, quiz_type)` — `en_to_de` / `de_to_en` /
      `multiple_choice` / `article`; non-nouns skipped for `article`; MC
      distractors are same-CEFR nearest-frequency words, deterministically shuffled
- [x] Stateless `question_id`: base64url(JSON of word id + type + reference +
      prompt), decoded by `evaluate_answer` — no server-side question store
- [x] `evaluate_answer` — exact / fuzzy (`difflib` ratio + edit-distance rescue
      for short words) for constrained types; **Anthropic API** semantic grading
      for `de_to_en`, degrading to fuzzy (method `semantic_fallback_fuzzy`) when
      no credentials / API error. Returns correct + score + rationale + expected.
- [x] `create_learning_session` — `scheduler.create_learning_session` (new):
      `build_session` + a persisted `sessions` row; tool returns a hydrated
      `SessionView`
- [x] `update_learning_state` — wraps `scheduler.update_after_review`, returns the
      word's new `CardStateView`. `update_after_review` now raises `LookupError`
      for unknown user/word (SQLite doesn't enforce the FKs)
- [x] `.env.example` grader model default → `claude-opus-5` (per the claude-api
      skill; sonnet noted as a cheaper option), read from `ANTHROPIC_MODEL`
- **AC met:** quiz round-trip + free-text grading covered by
  `backend/mcp_servers/tests/` (`test_quiz`, `test_grading` incl. a fake LLM
  client, `test_learning_server` end-to-end). 441 tests pass, core 100%. All 8
  tools verified listed over a real MCP HTTP session.

> Next: `LG-08` — vocab MCP **resource** + standalone MCP-Inspector/client
> sign-off + trace every tool call.

### Day 8 — `LG-08` MCP server #1 — resource + standalone sign-off  `[x]`
- [x] Vocab exposed as MCP **resources**: `vocab://words` (static overview),
      `vocab://words/{cefr_level}` and `vocab://word/{lemma}` (templates).
      Missing word → `ResourceNotFoundError`; bad level → `ResourceError`.
- [x] Every tool call **and** resource read wrapped with `tracer.trace_tool_call`
      (name / input / output preview / latency / success) → JSONL. `build_server`
      takes an optional `Tracer`; `tracer.py` resolves `TRACE_LOG_PATH` lazily so
      it never touches the repo at import.
- [x] `test_standalone_client.py` — a real `ClientSession` over an in-memory
      transport does the full JSON-RPC dance (initialize, list tools/resources,
      read_resource, a study flow) **with no agent code**; a second test proves a
      bad call / missing resource is reported, not a crash, and the session stays
      usable. `smoke.py` is the human-runnable equivalent (verified against the
      real 3899-word seed).
- [x] docker-compose learning-mcp already serves streamable-http on :8100 (LG-06)
- **AC met (DoD §17):** server answers a full manual session independent of the
  agent. **448 tests pass, `backend/core` 100%**, ruff + black clean.

> **Build-order step 3 (MCP server #1) is complete.** Next: `LG-09`, the agent
> orchestrator.

### Day 9 — `LG-09` Agent orchestrator — intent + loop  `[x]`
- [x] `agent/mcp_client.py` — `MCPToolClient`: Anthropic-shaped `tool_specs()` +
      a sync, traced `call()` over an in-process `MCPServer` (principle #3, "even
      in-process"). One seam to swap for a real transport or wrap for failure
      injection; `MCPToolError` for tool errors.
- [x] `agent/orchestrator.py` — `run_session(request, *, mcp_client, llm_client,
      tracer)`: manual Anthropic tool-use loop. System prompt does the one NL
      step (minutes + topic) and forbids picking/sorting/inventing words. Loops
      through `create_learning_session`; `intent` = that call's args. `MAX_TURNS=8`
      guard; `refusal` / `no_session` / `max_turns` handled; tool errors fed back
      as `is_error` results, not raised.
- [x] Tracing: an `agent_decision` per LLM turn + `agent.tool_call.*` per call +
      the server's own `learning.tool.*` (shared tracer).
- [x] `python -m backend.agent "..." --user-id N` CLI.
- **AC met:** `test_orchestrator.py` drives the loop with a scripted `FakeLLM`
  (no network) — "I have 10 minutes, German for work" → tool sequence
  `[get_user_profile, create_learning_session]`, `intent {minutes 10, topic work}`,
  session composed, trace shows it. Error-recovery / max-turns / refusal /
  no-session covered. `test_orchestrator_live.py` is the real-API version
  (skipped without a key). 459 pass + 1 skipped.
- [x] CI split: a `core` job (minimal deps, `--cov-fail-under=90`, proves
      `backend/core` import-purity via `test_import_purity.py`) and a `full` job
      (`--extra agent`, whole suite).

### Day 10 — `LG-10` Agent — quiz + grade + update loop  `[x]`
- [x] System prompt extended: after `create_learning_session` the agent calls
      `create_quiz` once with the session's word ids. `SessionResult.quiz` carries
      the questions.
- [x] `grade_answer(mcp, *, user_id, question_id, user_answer)` — a fixed
      `evaluate_answer` → `update_learning_state` sequence, **no LLM turn** (the
      semantic grading lives inside the tool). Returns `AnswerFeedback`
      (correct/score/rationale/expected/method + the new `CardStateView`).
- [x] `LearningSession` (from `start_session`) — `.answer(qid, text)` per answer,
      `.summary()` → `{answered, correct, accuracy, ...}` and calls the new
      `finish_learning_session` MCP tool, which writes `sessions.words_covered`
      (scheduler `finish_session` + `read_models.summarise_session` +
      `SessionSummary`).
- [x] `python -m backend.agent "<req>" --auto` walks the whole flow.
- **AC met (DoD §17):** one NL request → composed session + quiz, each answer
  graded and applied, session summarised — all in the trace
  (`agent.turn` ×N, then `agent.tool_call.{evaluate_answer,update_learning_state}`
  per answer). `test_session_flow.py` + `test_orchestrator.py` drive it with a
  scripted LLM (fuzzy grading, no key). 465 pass + 1 skipped, `backend/core` 100%.

> **Build-order step 4 (agent + session flow) is complete.** Next: `LG-11`,
> MCP server #2.

---

## Week 3 — MCP server #2 + failure handling + simulator

### Day 11 — `LG-11` MCP server #2 (notes)  `[x]`
- [x] `backend/mcp_servers/secondary_server/` — its own `MCPServer("notes")`, own
      process (`python -m backend.mcp_servers.secondary_server`), own transport
      (stdio / `SECONDARY_MCP_TRANSPORT=streamable-http` on :8101), own storage
      (a filesystem Markdown vault, **not** Postgres). `test_secondary_server.py`
      AST-asserts it imports nothing from `learning_server` / `backend.core` /
      `backend.db` (principle #5).
- [x] `vault.py` — safe note names (traversal / absolute / weird chars rejected),
      `write_note` / `append_note` / `read_note` / `list_notes`, and
      `log_progress(summary, heading, date)` → appends a dated `## <date> — <h>`
      section to `progress.md` (the section-10 weekly-summary export).
- [x] 5 tools, each traced (`notes.tool.*`); errors → `ToolError`.
- [x] `SECONDARY_MCP_KIND=calendar` exits with a clear "not implemented" message.
- **AC met:** `test_standalone_client_secondary.py` drives a real `ClientSession`
  over an in-memory transport (list tools, write/append/read/log_progress/list,
  error survives) — independent of the agent and of server #1.
  HTTP transport verified binding :8101. 486 pass + 1 skipped.

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
