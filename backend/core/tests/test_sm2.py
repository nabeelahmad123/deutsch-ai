"""Pure SM-2 recurrence tests -- no DB, no network, fully deterministic."""

import pytest

from backend.core.scheduler import (
    INITIAL_EASE_FACTOR,
    MIN_EASE_FACTOR,
    CardState,
    quality_from_response,
    sm2_update,
)


def _run(qualities: list[int]) -> CardState:
    state = CardState()
    for q in qualities:
        state = sm2_update(state, q)
    return state


def test_first_three_successful_intervals():
    s1 = sm2_update(CardState(), 5)
    assert (s1.repetitions, s1.interval_days) == (1, 1)

    s2 = sm2_update(s1, 5)
    assert (s2.repetitions, s2.interval_days) == (2, 6)

    s3 = sm2_update(s2, 5)
    assert s3.repetitions == 3
    assert s3.interval_days == round(6 * s2.ease_factor)  # uses pre-update EF


def test_quality_4_leaves_ease_factor_unchanged():
    s = sm2_update(CardState(), 4)
    assert s.ease_factor == pytest.approx(INITIAL_EASE_FACTOR)


def test_failure_resets_repetitions_and_interval_but_lowers_ease():
    built = _run([5, 5, 4])
    assert built.repetitions == 3

    failed = sm2_update(built, 2)
    assert (failed.repetitions, failed.interval_days) == (0, 1)
    assert failed.ease_factor < built.ease_factor


def test_ease_factor_never_drops_below_floor():
    state = CardState()
    for _ in range(20):
        state = sm2_update(state, 3)  # passing, but the worst passing grade
    assert state.ease_factor == pytest.approx(MIN_EASE_FACTOR)
    assert state.ease_factor >= MIN_EASE_FACTOR


def test_known_reference_sequence():
    # [4, 4, 3, 5] worked by hand against the reference algorithm.
    state = _run([4, 4, 3, 5])
    assert state.repetitions == 4
    assert state.interval_days == 35
    assert state.ease_factor == pytest.approx(2.46)


@pytest.mark.parametrize("q", [-1, 6, 10])
def test_quality_out_of_range_raises(q):
    with pytest.raises(ValueError):
        sm2_update(CardState(), q)


def test_deterministic():
    assert _run([5, 3, 4, 2, 5, 5]) == _run([5, 3, 4, 2, 5, 5])


@pytest.mark.parametrize(
    ("correct", "rt_ms", "expected"),
    [
        (True, 0, 5),
        (True, 3000, 5),
        (True, 3001, 4),
        (True, 8000, 4),
        (True, 20_000, 3),
        (False, 100, 2),
        (False, 99_999, 2),
        (True, -50, 5),  # clamped
    ],
)
def test_quality_from_response(correct, rt_ms, expected):
    assert quality_from_response(correct, rt_ms) == expected
