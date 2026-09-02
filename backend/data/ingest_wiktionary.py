"""Enrich lemmas with gender, plural, and an English gloss from Wiktionary.

Source: German Wiktionary XML dumps
        https://dumps.wikimedia.org/dewiktionary/  (dewiktionary-latest-pages-articles.xml.bz2)
        English Wiktionary is used for the EN gloss.

Licensing: Wiktionary is CC BY-SA. We derive structured fields (article, plural,
translation_en) rather than redistributing article text.

Input : backend/data/build/frequency.jsonl  (from ingest_frequency.py)
Output: backend/data/build/words.jsonl with records
    {"lemma","article","plural","translation_en","frequency_rank","topic","ipa_or_audio_ref"}

Day-1 status: the dump streamer/parser is a TODO. `--sample` enriches the bundled
starter set from a small hand-built lexicon so the DB seed is real.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"

# Hand-built enrichment for the starter set. article/plural only for nouns.
# topic is left None here; topic tagging is a later step.
SAMPLE_LEXICON: dict[str, dict[str, str | None]] = {
    "Haus": {"article": "das", "plural": "Häuser", "translation_en": "house", "ipa": "haʊ̯s"},
    "Frau": {"article": "die", "plural": "Frauen", "translation_en": "woman; Mrs", "ipa": "fʁaʊ̯"},
    "Mann": {"article": "der", "plural": "Männer", "translation_en": "man", "ipa": "man"},
    "Kind": {"article": "das", "plural": "Kinder", "translation_en": "child", "ipa": "kɪnt"},
    "Jahr": {"article": "das", "plural": "Jahre", "translation_en": "year", "ipa": "jaːɐ̯"},
    "Tag": {"article": "der", "plural": "Tage", "translation_en": "day", "ipa": "taːk"},
    "Zeit": {"article": "die", "plural": "Zeiten", "translation_en": "time", "ipa": "t͡saɪ̯t"},
    "Hand": {"article": "die", "plural": "Hände", "translation_en": "hand", "ipa": "hant"},
    "Auge": {"article": "das", "plural": "Augen", "translation_en": "eye", "ipa": "ˈaʊ̯ɡə"},
    "Woche": {"article": "die", "plural": "Wochen", "translation_en": "week", "ipa": "ˈvɔxə"},
    "Wasser": {"article": "das", "plural": "Wasser", "translation_en": "water", "ipa": "ˈvasɐ"},
    "Stadt": {"article": "die", "plural": "Städte", "translation_en": "city", "ipa": "ʃtat"},
    "Land": {
        "article": "das",
        "plural": "Länder",
        "translation_en": "country; land",
        "ipa": "lant",
    },
    "Arbeit": {"article": "die", "plural": "Arbeiten", "translation_en": "work", "ipa": "ˈaʁbaɪ̯t"},
    "Leben": {"article": "das", "plural": "Leben", "translation_en": "life", "ipa": "ˈleːbn̩"},
    "Freund": {"article": "der", "plural": "Freunde", "translation_en": "friend", "ipa": "fʁɔɪ̯nt"},
    "Schule": {"article": "die", "plural": "Schulen", "translation_en": "school", "ipa": "ˈʃuːlə"},
    "Buch": {"article": "das", "plural": "Bücher", "translation_en": "book", "ipa": "buːx"},
    "Tisch": {"article": "der", "plural": "Tische", "translation_en": "table", "ipa": "tɪʃ"},
    "Tür": {"article": "die", "plural": "Türen", "translation_en": "door", "ipa": "tyːɐ̯"},
    "gehen": {"article": None, "plural": None, "translation_en": "to go", "ipa": "ˈɡeːən"},
    "kommen": {"article": None, "plural": None, "translation_en": "to come", "ipa": "ˈkɔmən"},
    "machen": {"article": None, "plural": None, "translation_en": "to do; make", "ipa": "ˈmaxn̩"},
    "sagen": {"article": None, "plural": None, "translation_en": "to say", "ipa": "ˈzaːɡn̩"},
    "sehen": {"article": None, "plural": None, "translation_en": "to see", "ipa": "ˈzeːən"},
    "geben": {"article": None, "plural": None, "translation_en": "to give", "ipa": "ˈɡeːbn̩"},
    "finden": {"article": None, "plural": None, "translation_en": "to find", "ipa": "ˈfɪndn̩"},
    "denken": {"article": None, "plural": None, "translation_en": "to think", "ipa": "ˈdɛŋkn̩"},
    "essen": {"article": None, "plural": None, "translation_en": "to eat", "ipa": "ˈɛsn̩"},
    "trinken": {"article": None, "plural": None, "translation_en": "to drink", "ipa": "ˈtʁɪŋkn̩"},
    "gut": {"article": None, "plural": None, "translation_en": "good", "ipa": "ɡuːt"},
    "groß": {"article": None, "plural": None, "translation_en": "big; tall", "ipa": "ɡʁoːs"},
    "klein": {"article": None, "plural": None, "translation_en": "small", "ipa": "klaɪ̯n"},
    "neu": {"article": None, "plural": None, "translation_en": "new", "ipa": "nɔɪ̯"},
    "alt": {"article": None, "plural": None, "translation_en": "old", "ipa": "alt"},
    "jung": {"article": None, "plural": None, "translation_en": "young", "ipa": "jʊŋ"},
    "schnell": {"article": None, "plural": None, "translation_en": "fast", "ipa": "ʃnɛl"},
    "langsam": {"article": None, "plural": None, "translation_en": "slow", "ipa": "ˈlaŋzaːm"},
    "schön": {"article": None, "plural": None, "translation_en": "beautiful; nice", "ipa": "ʃøːn"},
    "wichtig": {"article": None, "plural": None, "translation_en": "important", "ipa": "ˈvɪçtɪç"},
}


def enrich(record: dict, lexicon: dict) -> dict | None:
    """Attach enrichment fields to a {lemma, frequency_rank} record.

    Returns None if the lemma has no enrichment (function words in the starter
    set); the real Wiktionary path will look every lemma up instead.
    """
    entry = lexicon.get(record["lemma"])
    if entry is None:
        return None
    return {
        "lemma": record["lemma"],
        "article": entry["article"],
        "plural": entry["plural"],
        "translation_en": entry["translation_en"],
        "frequency_rank": record["frequency_rank"],
        "topic": None,
        "ipa_or_audio_ref": entry.get("ipa"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="enrich the bundled starter set only")
    parser.add_argument("--in", dest="in_path", type=Path, default=BUILD_DIR / "frequency.jsonl")
    parser.add_argument("--out", type=Path, default=BUILD_DIR / "words.jsonl")
    args = parser.parse_args()

    if not args.sample:
        raise NotImplementedError(
            "Wiktionary dump parsing not implemented yet; run with --sample for now."
        )

    if not args.in_path.exists():
        raise SystemExit(f"missing {args.in_path}; run ingest_frequency.py --sample first")

    records = [json.loads(line) for line in args.in_path.read_text(encoding="utf-8").splitlines()]
    enriched = [e for r in records if (e := enrich(r, SAMPLE_LEXICON)) is not None]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for e in enriched:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote {len(enriched)}/{len(records)} enriched records -> {args.out}")


if __name__ == "__main__":
    main()
