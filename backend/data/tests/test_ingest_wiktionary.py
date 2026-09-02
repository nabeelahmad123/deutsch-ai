"""Unit tests for the kaikki / Wiktextract enrichment parser."""

import json

from backend.data.ingest_wiktionary import build_from_kaikki

NOUN = {
    "word": "Haus",
    "lang_code": "de",
    "pos": "noun",
    "head_templates": [
        {"name": "de-noun", "args": {"1": "n,,^er"}, "expansion": "Haus n (plural Häuser)"}
    ],
    "forms": [
        {"form": "Hauses", "tags": ["genitive"]},
        {"form": "Häuser", "tags": ["plural"]},
    ],
    "sounds": [{"ipa": "[haʊ̯s]"}, {"audio": "De-Haus.ogg"}],
    "senses": [{"glosses": ["house, building"]}],
}
VERB = {
    "word": "gehen",
    "lang_code": "de",
    "pos": "verb",
    "sounds": [{"ipa": "/ˈɡeːən/"}],
    "senses": [{"glosses": ["to go, to walk"]}],
}
INFLECTED_NOUN = {  # a frequent token that is really just a plural form
    "word": "Kinder",
    "lang_code": "de",
    "pos": "noun",
    "head_templates": [{"name": "de-noun", "args": {"1": "n"}, "expansion": "Kinder n"}],
    "senses": [{"glosses": ["nominative/accusative/genitive plural of Kind"]}],
}
NON_GERMAN = {"word": "gehen", "lang_code": "nl", "pos": "verb", "senses": [{"glosses": ["x"]}]}


def _write(tmp_path, *entries):
    p = tmp_path / "kaikki.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")
    return p


def test_noun_gender_plural_gloss_ipa(tmp_path):
    lex = build_from_kaikki(_write(tmp_path, NOUN), {"Haus"})
    assert lex["Haus"] == {
        "article": "das",
        "plural": "Häuser",
        "translation_en": "house, building",
        "ipa": "haʊ̯s",
    }


def test_verb_has_no_article_or_plural(tmp_path):
    lex = build_from_kaikki(_write(tmp_path, VERB), {"gehen"})
    assert lex["gehen"]["article"] is None
    assert lex["gehen"]["plural"] is None
    assert lex["gehen"]["translation_en"] == "to go, to walk"


def test_inflected_form_noun_gets_no_article(tmp_path):
    lex = build_from_kaikki(_write(tmp_path, INFLECTED_NOUN), {"Kinder"})
    assert lex["Kinder"]["article"] is None
    assert lex["Kinder"]["plural"] is None


def test_noun_entry_wins_over_verb_entry(tmp_path):
    both = {**VERB, "word": "Haus"}
    lex = build_from_kaikki(_write(tmp_path, both, NOUN), {"Haus"})
    assert lex["Haus"]["article"] == "das"


def test_only_wanted_german_lemmas_are_kept(tmp_path):
    lex = build_from_kaikki(_write(tmp_path, NOUN, VERB, NON_GERMAN), {"Haus"})
    assert set(lex) == {"Haus"}
