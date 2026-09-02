"""Enrich lemmas with gender, plural, an English gloss, and IPA from Wiktionary.

Source: English Wiktionary, German entries, pre-extracted with Wiktextract and
        published as JSONL by kaikki.org
        https://kaikki.org/dictionary/German/  (kaikki.org-dictionary-German.jsonl)

Licensing (CC BY-SA, see backend/data/README.md): we derive structured fields
(article, plural, translation_en, ipa) rather than redistributing article prose.

Input : backend/data/build/frequency.jsonl  (from ingest_frequency.py)
Output: backend/data/build/words.jsonl with records
    {"lemma","article","plural","translation_en","frequency_rank","topic","ipa_or_audio_ref"}

`--sample` enriches the bundled starter set from a small hand-built lexicon (no
download needed). `--kaikki <path>` parses the real extract.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"

# Gender letter (kaikki de-noun head template arg / expansion) -> article.
_GENDER_TO_ARTICLE = {"m": "der", "f": "die", "n": "das"}
# Prefer the most useful part of speech when a lemma has several entries.
_POS_PRIORITY = {"noun": 0, "verb": 1, "adj": 2, "adv": 3, "num": 4, "pron": 5}
_PLURAL_FROM_EXPANSION = re.compile(r"\bplural (\w[\w'’-]*)")
# Glosses that are just "this is an inflected form of X" carry no meaning of
# their own; skip them when the entry has a real definition too.
_FORM_OF_RE = re.compile(
    r"^(inflection of\b|.*\b(inflection|gerund|participle|"
    r"singular|plural|dative|genitive|accusative|nominative|superlative|comparative) of\b)",
    re.IGNORECASE,
)

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


# --- kaikki / Wiktextract parsing --------------------------------------------


def _clean_ipa(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().strip("/[]").strip() or None


def _gender_article(entry: dict) -> str | None:
    heads = entry.get("head_templates") or []
    if heads:
        arg1 = (heads[0].get("args") or {}).get("1", "")
        first = arg1.split(",", 1)[0].strip().lower()
        if first in _GENDER_TO_ARTICLE:
            return _GENDER_TO_ARTICLE[first]
        expansion = heads[0].get("expansion", "")
        m = re.search(r"\b([mfn])\b", expansion)
        if m:
            return _GENDER_TO_ARTICLE[m.group(1)]
    for form in entry.get("forms") or []:
        tags = set(form.get("tags") or [])
        if "canonical" in tags:
            for g, art in (("masculine", "der"), ("feminine", "die"), ("neuter", "das")):
                if g in tags:
                    return art
    return None


def _plural(entry: dict) -> str | None:
    for form in entry.get("forms") or []:
        if form.get("tags") == ["plural"] and form.get("form") not in {"-", "no plural"}:
            return form["form"]
    for form in entry.get("forms") or []:
        tags = set(form.get("tags") or [])
        if "plural" in tags and "nominative" in tags and "definite" not in tags:
            return form.get("form")
    heads = entry.get("head_templates") or []
    if heads:
        m = _PLURAL_FROM_EXPANSION.search(heads[0].get("expansion", ""))
        if m:
            return m.group(1)
    return None


def _glosses(entry: dict) -> tuple[str | None, bool]:
    """Return (best gloss, has_real_definition).

    ``has_real_definition`` is False when every sense is just a "form of X"
    pointer -- a sign this entry is an inflected form, not the lemma itself.
    """
    glosses = [
        g.strip().rstrip(":").strip()
        for sense in entry.get("senses") or []
        for g in sense.get("glosses") or []
        if g.strip()
    ]
    if not glosses:
        return None, False
    real = [g for g in glosses if not _FORM_OF_RE.match(g)]
    if real:
        return real[0][:256], True
    return glosses[0][:256], False


def _ipa(entry: dict) -> str | None:
    for sound in entry.get("sounds") or []:
        cleaned = _clean_ipa(sound.get("ipa"))
        if cleaned:
            return cleaned
    return None


def iter_kaikki(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_from_kaikki(path: Path, lemmas: set[str]) -> dict[str, dict]:
    """Return {lemma: enrichment dict} for the wanted lemmas, best entry per lemma.

    "Best" = highest-priority part of speech (noun > verb > adj > ...); the first
    such entry in the file wins, which is stable across runs.
    """
    chosen: dict[str, tuple[int, dict]] = {}
    for entry in iter_kaikki(path):
        word = entry.get("word")
        if word not in lemmas or entry.get("lang_code") != "de":
            continue
        rank = _POS_PRIORITY.get(entry.get("pos", ""), 99)
        if word in chosen and chosen[word][0] <= rank:
            continue
        gloss, is_real = _glosses(entry)
        # A noun whose only senses are "plural of X" etc. is an inflected form,
        # not a headword -- don't hang an article/plural off it.
        is_noun = entry.get("pos") == "noun" and is_real
        chosen[word] = (
            rank,
            {
                "article": _gender_article(entry) if is_noun else None,
                "plural": _plural(entry) if is_noun else None,
                "translation_en": gloss,
                "ipa": _ipa(entry),
            },
        )
    return {word: data for word, (_rank, data) in chosen.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="enrich the bundled starter set only")
    parser.add_argument("--kaikki", type=Path, help="kaikki.org German Wiktextract JSONL")
    parser.add_argument("--in", dest="in_path", type=Path, default=BUILD_DIR / "frequency.jsonl")
    parser.add_argument("--out", type=Path, default=BUILD_DIR / "words.jsonl")
    args = parser.parse_args()

    if not args.in_path.exists():
        raise SystemExit(f"missing {args.in_path}; run ingest_frequency.py first")
    records = [json.loads(line) for line in args.in_path.read_text(encoding="utf-8").splitlines()]

    if args.sample and not args.kaikki:
        enriched = [e for r in records if (e := enrich(r, SAMPLE_LEXICON)) is not None]
    else:
        kaikki_path = args.kaikki or (Path(__file__).parent / "raw" / "kaikki-de.jsonl")
        if not kaikki_path.exists():
            raise SystemExit(
                f"missing {kaikki_path}; download it (see backend/data/README.md) or use --sample"
            )
        wanted = {r["lemma"] for r in records}
        lex = build_from_kaikki(kaikki_path, wanted)
        enriched = []
        for r in records:
            data = lex.get(r["lemma"])
            if data is None or not data.get("translation_en"):
                continue  # no usable Wiktionary entry -> drop (keeps the table clean)
            enriched.append(
                {
                    "lemma": r["lemma"],
                    "article": data["article"],
                    "plural": data["plural"],
                    "translation_en": data["translation_en"],
                    "frequency_rank": r["frequency_rank"],
                    "topic": None,
                    "ipa_or_audio_ref": data["ipa"],
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for e in enriched:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote {len(enriched)}/{len(records)} enriched records -> {args.out}")


if __name__ == "__main__":
    main()
