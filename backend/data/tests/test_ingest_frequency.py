"""Unit tests for the Leipzig frequency parser. Pure stdlib, no downloads."""

from backend.data.ingest_frequency import (
    build_from_raw,
    load_crosscheck,
    spearman_against_crosscheck,
)

# id <TAB> word <TAB> frequency  -- Leipzig *-words.txt layout, id-ordered.
RAW = "\n".join(
    [
        "1\t.\t999999",  # punctuation -> dropped
        "2\tund\t5000",
        "3\tHaus\t900",
        "4\thaus\t100",  # case-variant of "Haus" -> collapsed
        "5\tCOVID19\t400",  # has digits -> dropped
        "6\tarbeiten\t800",
        "7\tzu-\t50",  # trailing hyphen -> dropped
        "8\tA\t700",  # length 1 -> dropped
        "9\tSchule\t600",
        "10\tblah",  # malformed (no freq) -> skipped
    ]
)


def test_filters_and_ranks_by_frequency():
    assert build_from_raw(RAW.splitlines(), top_n=10) == [
        "und",
        "Haus",
        "arbeiten",
        "Schule",
    ]


def test_case_variants_collapse_to_most_frequent_surface_form():
    out = build_from_raw(RAW.splitlines(), top_n=10)
    assert "Haus" in out and "haus" not in out


def test_top_n_cut():
    assert build_from_raw(RAW.splitlines(), top_n=2) == ["und", "Haus"]


def test_deterministic():
    lines = RAW.splitlines()
    assert build_from_raw(lines, top_n=5) == build_from_raw(lines, top_n=5)


def test_crosscheck_load_and_spearman(tmp_path):
    p = tmp_path / "cc.txt"
    p.write_text("und 10\nhaus 9\narbeiten 8\nschule 7\n", encoding="utf-8")
    ranks = load_crosscheck(p)
    assert ranks["und"] == 1 and ranks["schule"] == 4
    # < 20 shared lemmas -> None rather than a noisy correlation
    assert spearman_against_crosscheck(["und", "Haus"], ranks) is None
