# Design notes

Why the system is built the way it is. For the "what's where" view, see
[ARCHITECTURE.md](ARCHITECTURE.md).

## The problem

Spaced-repetition apps make you drive: pick a deck, pick a length, grind. I
wanted the entry point to be a sentence — *"I have 10 minutes, German for work"* —
and have an agent turn that into a session. But the moment you let an LLM near a
learning system, the temptation is to let it decide *what* to review. That's the
one thing it should not do: which cards are due, and when to show them again, is
a solved problem with a deterministic algorithm, and it needs to be reproducible
and testable.

So the shape is: **the LLM does the language, a deterministic core does the
scheduling, and MCP tools are the seam between them.**

## The rules I held to

1. **The scheduler has no LLM dependency.** `backend/core` imports no
   `anthropic`, no `mcp`, no `httpx` — a test walks the AST to prove it, and one
   CI job installs none of those packages. Given the same review history it
   always returns the same session.
2. **The agent never computes a schedule.** Its system prompt forbids picking,
   reordering or inventing words, or computing review dates. It infers *minutes*
   and *topic*, then calls `create_learning_session`. That's the only judgement
   it makes.
3. **The agent reaches data only through MCP tools** — even though the MCP
   server runs in-process. No `backend.db` import anywhere under `backend/agent`.
4. **Every tool call and agent decision is traced** — name, input, output,
   latency, ok/fail — as JSON lines, from the first commit rather than bolted on.
5. **The two MCP servers are separate processes.** Different packages, entry
   points, transports and storage (Postgres vs. a filesystem vault). A test
   asserts the notes server imports nothing from the learning server or the core.
   This is what makes "orchestrate across two tool surfaces" a real exercise
   instead of two modules in a trench coat.

## Data model

```
words(id, lemma, article, plural, translation_en, cefr_level, frequency_rank, topic, ipa_or_audio_ref)
users(id, created_at, target, username, password_hash)
review_logs(id, user_id, word_id, timestamp, correct, response_time_ms, source, error_type)
card_states(user_id, word_id, repetitions, ease_factor, interval_days, reviews, correct_reviews, last_reviewed, due_at)
sessions(id, user_id, started_at, duration_minutes_requested, words_covered, topic)
```

`review_logs` is the source of truth. Per-card SM-2 state isn't stored as such —
it's the fold of `sm2_update` over a card's logs. `card_states` is a cache of
that fold so the due-list and dashboard reads are indexed look-ups, not a replay
in Python on every request; it's rebuildable from the logs at any time.

CEFR level is approximated from frequency band (top ~500 ≈ A1, and so on) and
topic from a gloss-keyword tagger. Both are approximations and are documented as
such — not authoritative labels.

## Scope

- **A1–B2 only.** CEFR-tagging quality falls off a cliff past B2 and it adds no
  engineering value here.
- ~4,000 frequency-ranked words (Leipzig corpus for frequency, Wiktionary for
  gender/plural/glosses/IPA). Derived, not redistributed verbatim.
- Pronunciation is an IPA string from Wiktionary; no audio dataset.

## How it's evaluated

Three separate harnesses, because "it demos" isn't evidence:

- **Learner model** — a synthetic learner simulator drives SM-2 vs. a Half-Life
  Regression model vs. random, scoring retention and calibration (Brier,
  log-loss, AUC). The offline SM-2 number is cross-checked against a real
  `review_logs` table driven by the actual scheduler. → `docs/EVALUATION.md`
- **Agent** — ~12 labelled natural-language requests scored on intent parsing,
  tool-call sequence, and session sanity checked against the DB.
  → `docs/AGENT_EVAL.md`
- **Failure handling** — timeouts, malformed tool responses and stripped-down
  ambiguous requests are injected into real agent runs, and the recovery
  disposition is classified and counted. → `docs/FAILURE_RECOVERY.md`

## Deliberately not in scope

Full CEFR range (C1/C2); a multi-agent framework (one well-scoped agent is the
right size for this); RL for scheduling; deep knowledge tracing; my own STT or
pronunciation scoring; fine-tuning; gamification; a mobile app; building a
translation corpus from scratch.

## What I'd change with more time

- The agent is narrow on purpose, but a genuinely multi-step flow (read the
  week's mistakes → plan several sessions → write them to the vault) would show
  more of the orchestration.
- Topic inference on vague requests ("study German" with no subject) is the
  shakiest part — the agent eval documents it.
- Tracing is JSON lines; a Langfuse/OTel exporter behind the same interface
  would make multi-run analysis easier.
