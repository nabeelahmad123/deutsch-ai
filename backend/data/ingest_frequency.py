"""Ingest a frequency-ranked German word list.

Primary source : Leipzig Corpora Collection / Deutscher Wortschatz
                 https://wortschatz.uni-leipzig.de/en/download/German
Cross-check    : SUBTLEX-DE
                 http://crr.ugent.be/programs-data/subtitle-frequencies/subtlex-de

Licensing (CLAUDE.md section 6): do NOT redistribute either list verbatim.
This script reads a locally downloaded raw file and DERIVES a normalized table
(lemma, frequency_rank). The raw files are gitignored (backend/data/raw/).

Output: newline-delimited JSON at backend/data/build/frequency.jsonl with records
    {"lemma": str, "frequency_rank": int}

Day-1 status: the parser for the Leipzig word/co-occurrence archive format is a
TODO; `--sample` emits the bundled starter set so downstream steps and the DB
seed have data to work with.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"
RAW_DIR = Path(__file__).parent / "raw"

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


def build_from_raw(raw_path: Path) -> list[str]:
    """Parse a downloaded Leipzig word-frequency file into a rank-ordered list.

    TODO: implement for the actual Leipzig archive layout
    (``*-words.txt``: ``rank<TAB>word<TAB>freq``).
    """
    raise NotImplementedError(
        f"Leipzig raw parser not implemented yet. Place the download in {raw_path} "
        "and implement build_from_raw(); use --sample in the meantime."
    )


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
    parser.add_argument("--sample", action="store_true", help="use the bundled starter set")
    parser.add_argument("--raw", type=Path, default=RAW_DIR / "leipzig-de-words.txt")
    parser.add_argument("--out", type=Path, default=BUILD_DIR / "frequency.jsonl")
    args = parser.parse_args()

    lemmas = SAMPLE if args.sample else build_from_raw(args.raw)
    write_jsonl(lemmas, args.out)


if __name__ == "__main__":
    main()
