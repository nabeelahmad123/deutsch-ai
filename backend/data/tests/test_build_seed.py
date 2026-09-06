"""build_seed filtering + post-filter CEFR banding (pure, no build artifacts)."""

from backend.data.build_seed import is_study_word, iter_study_words


def _rec(lemma, gloss, rank):
    return {"lemma": lemma, "translation_en": gloss, "frequency_rank": rank}


def test_is_study_word_drops_function_and_grammatical_entries():
    assert is_study_word(_rec("Haus", "house", 1))
    assert not is_study_word(_rec("der", "the", 1))
    assert not is_study_word(_rec("Kindes", "genitive singular of Kind", 1))


def test_cefr_is_ranked_among_survivors_not_raw_tokens():
    # der / die are dropped; Haus and Frau become study-ranks 1 and 2 -> A1
    recs = [
        _rec("der", "the", 1),
        _rec("Haus", "house", 2),
        _rec("die", "the", 3),
        _rec("Frau", "woman", 4),
    ]
    assert [(r["lemma"], lvl) for r, lvl in iter_study_words(recs)] == [
        ("Haus", "A1"),
        ("Frau", "A1"),
    ]


def test_bands_are_500_1000_1500_1000_then_stop():
    recs = [_rec(f"w{i}", f"word {i}", i) for i in range(1, 5000)]
    got = list(iter_study_words(recs))
    levels = [lvl for _r, lvl in got]
    assert len(got) == 4000
    assert (levels.count("A1"), levels.count("A2"), levels.count("B1"), levels.count("B2")) == (
        500,
        1000,
        1500,
        1000,
    )


def test_raw_frequency_rank_is_preserved_on_the_record():
    recs = [_rec("und", "and", 1), _rec("Jahr", "year", 2)]
    rec, level = next(iter(iter_study_words(recs)))
    assert rec["lemma"] == "Jahr" and rec["frequency_rank"] == 2 and level == "A1"
