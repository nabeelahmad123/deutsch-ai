"""Ingest a frequency-ranked German word list.

Primary source : Leipzig Corpora Collection / Deutscher Wortschatz
                 https://wortschatz.uni-leipzig.de/en/download/German
                 (deu_news_2024_1M.tar.gz -> deu_news_2024_1M-words.txt)
Cross-check    : OpenSubtitles word frequencies (stands in for SUBTLEX-DE, which
                 needs a manual form download); Spearman rank correlation logged.

Licensing: do NOT redistribute
either list verbatim. This script reads a locally downloaded raw file and DERIVES
a normalized table (lemma, frequency_rank) -- surface form + rank only, no counts.
The raw files are gitignored (backend/data/raw/).

Output: newline-delimited JSON at backend/data/build/frequency.jsonl with records
    {"lemma": str, "frequency_rank": int}

`--sample` emits the bundled starter set (no download needed); `--source leipzig`
reads the real archive.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import tarfile
from collections.abc import Iterable
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"
RAW_DIR = Path(__file__).parent / "raw"

# ~7,500 raw tokens so that, after function words / grammatical-only entries and
# lemmas with no Wiktionary entry are filtered out (build_seed.iter_study_words),
# ~4,000 study words remain -- exactly enough to fill the A1-B2 bands.
DEFAULT_TOP_N = 7500

# A valid German word token: starts and ends with a letter, letters + interior
# hyphen only, length >= 2. Excludes punctuation, digits, initials, abbreviations.
_LETTER = "A-Za-zÄÖÜäöüßẞ"
TOKEN_RE = re.compile(rf"^[{_LETTER}][{_LETTER}\-]*[{_LETTER}]$")

# A tiny, hand-checked starter set (top-frequency German lemmas). Enough to seed
# the DB and exercise the pipeline end to end before the full ~4k list lands.
SAMPLE: list[str] = [
    "der",
    "die",
    "und",
    "in",
    "das",
    "nicht",
    "von",
    "sie",
    "ist",
    "des",
    "sich",
    "mit",
    "dem",
    "dass",
    "er",
    "es",
    "ein",
    "ich",
    "auf",
    "so",
    "eine",
    "auch",
    "als",
    "an",
    "nach",
    "wie",
    "im",
    "für",
    "man",
    "aber",
    "aus",
    "durch",
    "wenn",
    "nur",
    "war",
    "noch",
    "werden",
    "bei",
    "hat",
    "wir",
    "was",
    "wird",
    "sein",
    "einen",
    "welche",
    "sind",
    "oder",
    "zur",
    "um",
    "haben",
    "Haus",
    "Frau",
    "Mann",
    "Kind",
    "Jahr",
    "Tag",
    "Zeit",
    "Hand",
    "Auge",
    "Woche",
    "Wasser",
    "Stadt",
    "Land",
    "Arbeit",
    "Leben",
    "Freund",
    "Schule",
    "Buch",
    "Tisch",
    "Tür",
    "gehen",
    "kommen",
    "machen",
    "sagen",
    "sehen",
    "geben",
    "finden",
    "denken",
    "essen",
    "trinken",
    "gut",
    "groß",
    "klein",
    "neu",
    "alt",
    "jung",
    "schnell",
    "langsam",
    "schön",
    "wichtig",
]


def _is_wordlike(token: str) -> bool:
    return len(token) >= 2 and TOKEN_RE.match(token) is not None


def build_from_raw(lines: Iterable[str], top_n: int = DEFAULT_TOP_N) -> list[str]:
    """Turn Leipzig ``*-words.txt`` lines into a rank-ordered lemma list.

    Line format: ``word_id<TAB>word<TAB>frequency`` (the file is sorted by id,
    not frequency). We filter to word-like tokens, sort by descending frequency
    with the token as a deterministic tie-breaker, collapse case-variants
    keeping the most frequent surface form, and keep the top ``top_n``.
    """
    best: dict[str, tuple[int, str]] = {}  # casefold -> (frequency, surface form)
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        _id, word, freq_str = parts[0], parts[1], parts[2]
        try:
            freq = int(freq_str)
        except ValueError:
            continue
        if not _is_wordlike(word):
            continue
        key = word.casefold()
        current = best.get(key)
        if current is None or freq > current[0]:
            best[key] = (freq, word)

    ranked = sorted(best.values(), key=lambda fw: (-fw[0], fw[1]))
    return [word for _freq, word in ranked[:top_n]]


def extract_leipzig_words(archive_path: Path) -> list[str]:
    """Return the lines of the ``*-words.txt`` member of a Leipzig tar.gz."""
    with tarfile.open(archive_path, "r:*") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith("-words.txt")), None)
        if member is None:
            raise SystemExit(f"no *-words.txt inside {archive_path}")
        fh = tar.extractfile(member)
        if fh is None:
            raise SystemExit(f"could not read {member.name}")
        return io.TextIOWrapper(fh, encoding="utf-8", errors="replace").read().splitlines()


def load_crosscheck(path: Path) -> dict[str, int]:
    """Load an OpenSubtitles-style ``word count`` list -> {word: rank} (1-based)."""
    ranks: dict[str, int] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        word = line.split(" ", 1)[0].strip().casefold()
        if word and word not in ranks:
            ranks[word] = i
    return ranks


def spearman_against_crosscheck(lemmas: list[str], crosscheck: dict[str, int]) -> float | None:
    """Spearman rho between our ranking and the cross-check, over shared vocab."""
    import numpy as np

    ours, theirs = [], []
    for rank, lemma in enumerate(lemmas, start=1):
        other = crosscheck.get(lemma.casefold())
        if other is not None:
            ours.append(rank)
            theirs.append(other)
    if len(ours) < 20:
        return None
    a = np.argsort(np.argsort(ours))
    b = np.argsort(np.argsort(theirs))
    return float(np.corrcoef(a, b)[0, 1])


def write_jsonl(lemmas: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rank, lemma in enumerate(lemmas, start=1):
            fh.write(
                json.dumps({"lemma": lemma, "frequency_rank": rank}, ensure_ascii=False) + "\n"
            )
    print(f"wrote {len(lemmas)} records -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("sample", "leipzig"),
        default="sample",
        help="'sample' = bundled starter set; 'leipzig' = read --archive/--raw",
    )
    parser.add_argument("--sample", action="store_true", help="alias for --source sample")
    parser.add_argument(
        "--archive",
        type=Path,
        default=RAW_DIR / "leipzig_deu_news_2024_1M.tar.gz",
        help="Leipzig corpus tar.gz",
    )
    parser.add_argument("--raw", type=Path, help="pre-extracted *-words.txt (overrides --archive)")
    parser.add_argument("--crosscheck", type=Path, help="OpenSubtitles-style 'word count' list")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--out", type=Path, default=BUILD_DIR / "frequency.jsonl")
    args = parser.parse_args()

    if args.sample or args.source == "sample":
        lemmas = SAMPLE[: args.top]
    else:
        if args.raw:
            lines = args.raw.read_text(encoding="utf-8", errors="replace").splitlines()
        elif args.archive.exists():
            lines = extract_leipzig_words(args.archive)
        else:
            raise SystemExit(
                f"missing {args.archive}; download it (see backend/data/README.md) "
                "or use --source sample"
            )
        lemmas = build_from_raw(lines, top_n=args.top)

    write_jsonl(lemmas, args.out)

    if args.crosscheck and args.crosscheck.exists():
        rho = spearman_against_crosscheck(lemmas, load_crosscheck(args.crosscheck))
        if rho is None:
            print("cross-check: too little shared vocab to compare")
        else:
            print(f"cross-check: Spearman rho vs. {args.crosscheck.name} = {rho:.3f}")


if __name__ == "__main__":
    main()
