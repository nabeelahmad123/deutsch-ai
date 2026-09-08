# Data sources & licensing

Scope: A1–B2 only, ~4,000 frequency-ranked words, CEFR approximated
from frequency band. **Check licensing before redistributing any list verbatim —
regenerate/derive rather than copy wholesale where the license is unclear.**

The pipeline downloads raw sources into `backend/data/raw/` (gitignored) and emits
**derived** artifacts into `backend/data/build/` (also gitignored). Only
`seed.sql` — a derived table of ~4k lemmas with structured fields — is committed.

## Frequency ranking

| Source | File | License | Use |
|---|---|---|---|
| Leipzig Corpora Collection / Deutscher Wortschatz | `deu_news_2024_1M.tar.gz` → `*-words.txt` | CC BY-NC 4.0 | **primary** frequency ranking |
| OpenSubtitles word frequencies (hermitdave/FrequencyWords) | `de_50k.txt` | MIT | **cross-check** (Spearman ρ vs. Leipzig); stands in for SUBTLEX-DE, which needs a manual form download from crr.ugent.be |

We do not redistribute either list. `ingest_frequency.py` reads the raw file,
derives a rank-ordered lemma list (surface form + rank only, no counts), filters
to plausible German word tokens, and keeps the top N.

Leipzig CC BY-NC attribution: *D. Goldhahn, T. Eckart & U. Quasthoff:
Building Large Monolingual Dictionaries at the Leipzig Corpora Collection,
LREC 2012.*

## Enrichment (gender, plural, definitions, IPA)

| Source | File | License |
|---|---|---|
| English Wiktionary, German entries, via Wiktextract (kaikki.org) | `kaikki.org-dictionary-German.jsonl` | CC BY-SA 4.0 / GFDL |

Wiktionary is CC BY-SA. `ingest_wiktionary.py` parses the pre-extracted JSONL and
derives structured fields (`article`, `plural`, `translation_en`,
`ipa_or_audio_ref`) — it does not copy article prose. Attribution: German
Wiktionary contributors, https://de.wiktionary.org, CC BY-SA 4.0.

## Pronunciation

No audio dataset. We store an IPA transcription from Wiktionary; audio
is generated on demand via a TTS API later, if in scope.

## Reproducibility

Re-running the pipeline against the same cached `raw/` files is deterministic
(stable sort, fixed filters, fixed top-N cut). Delete `raw/` to re-fetch.

```
python -m backend.data.ingest_frequency  --source leipzig \
    --archive backend/data/raw/leipzig_deu_news_2024_1M.tar.gz \
    --crosscheck backend/data/raw/de_50k.txt --top 4000
python -m backend.data.ingest_wiktionary --kaikki backend/data/raw/kaikki-de.jsonl
python -m backend.data.build_seed
```

`--sample` on either script uses a small bundled starter set and needs no
downloads (used by CI and for a quick local bootstrap).
