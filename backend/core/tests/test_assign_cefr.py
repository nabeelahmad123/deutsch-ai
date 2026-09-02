"""Tests for the frequency-band -> CEFR approximation.

``assign_cefr`` lives in ``backend/data`` but is pure and dependency-free, so it
runs in the core CI job alongside the scheduler tests.
"""

import pytest

from backend.data.assign_cefr import MAX_RANK_IN_SCOPE, assign_cefr


@pytest.mark.parametrize(
    ("rank", "expected"),
    [
        (1, "A1"),
        (500, "A1"),
        (501, "A2"),
        (1500, "A2"),
        (1501, "B1"),
        (3000, "B1"),
        (3001, "B2"),
        (4000, "B2"),
    ],
)
def test_band_boundaries(rank, expected):
    assert assign_cefr(rank) == expected


def test_out_of_scope_above_b2():
    assert assign_cefr(MAX_RANK_IN_SCOPE + 1) is None
    assert assign_cefr(10_000) is None


def test_rejects_non_positive_rank():
    with pytest.raises(ValueError):
        assign_cefr(0)
