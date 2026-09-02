"""Property-style tests for the SM-2 recurrence over many seeded random inputs.

No hypothesis dependency -- a fixed-seed RNG keeps these deterministic and
CI-stable while still covering a wide space of grade sequences.
"""

import random

import pytest

from backend.core.scheduler import (
    MIN_EASE_FACTOR,
    PASS_QUALITY_THRESHOLD,
    CardState,
    sm2_update,
)


def _sequence(seed: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(0, 5) for _ in range(rng.randint(1, 40))]


SEQUENCES = [_sequence(seed) for seed in range(300)]


@pytest.mark.parametrize("grades", SEQUENCES, ids=[f"seq{i}" for i in range(len(SEQUENCES))])
def test_invariants_hold_for_any_grade_sequence(grades):
    state = CardState()
    for q in grades:
        prev = state
        state = sm2_update(state, q)

        assert state.ease_factor >= MIN_EASE_FACTOR
        assert state.repetitions >= 0
        assert state.interval_days >= 1

        if q < PASS_QUALITY_THRESHOLD:
            assert state.repetitions == 0
            assert state.interval_days == 1
        else:
            assert state.repetitions == prev.repetitions + 1
            # a successful review never shortens the interval
            assert state.interval_days >= prev.interval_days or prev.repetitions == 0


def test_all_passing_grades_give_monotonic_nondecreasing_intervals():
    for seed in range(100):
        rng = random.Random(seed)
        state = CardState()
        last_interval = 0
        for _ in range(30):
            q = rng.randint(PASS_QUALITY_THRESHOLD, 5)
            state = sm2_update(state, q)
            assert state.interval_days >= last_interval
            last_interval = state.interval_days


def test_repeated_failures_keep_state_at_floor():
    state = CardState()
    for _ in range(50):
        state = sm2_update(state, 0)
    assert state.repetitions == 0
    assert state.interval_days == 1
    assert state.ease_factor == pytest.approx(MIN_EASE_FACTOR)


def test_full_recurrence_is_reproducible():
    grades = [random.Random(1234).randint(0, 5) for _ in range(60)]

    def run():
        st = CardState()
        for q in grades:
            st = sm2_update(st, q)
        return st

    assert run() == run()
