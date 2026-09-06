"""Frequency-band -> approximate CEFR tag.

This is an APPROXIMATION, not an authoritative CEFR classification (CLAUDE.md
section 6). The rank passed in is the word's position among *study words* -- i.e.
after function words and bare grammatical inflections are filtered out (see
backend/data/build_seed.py:iter_study_words) -- so the bands describe useful
vocabulary, not raw corpus tokens. Cumulative:

    rank <=  500  -> A1
    rank <= 1500  -> A2
    rank <= 3000  -> B1
    rank <= 4000  -> B2
    rank >  4000  -> out of scope (A1-B2 only, section 6)

Pure function, no dependencies, unit-tested.
"""

from __future__ import annotations

# (inclusive upper bound on frequency_rank, level)
_BANDS: tuple[tuple[int, str], ...] = (
    (500, "A1"),
    (1500, "A2"),
    (3000, "B1"),
    (4000, "B2"),
)

MAX_RANK_IN_SCOPE = _BANDS[-1][0]


def assign_cefr(frequency_rank: int) -> str | None:
    """Return "A1".."B2", or None if the rank is outside the A1-B2 scope.

    Raises ValueError for a non-positive rank (ranks are 1-based).
    """
    if frequency_rank < 1:
        raise ValueError(f"frequency_rank must be >= 1, got {frequency_rank}")
    for upper, level in _BANDS:
        if frequency_rank <= upper:
            return level
    return None
