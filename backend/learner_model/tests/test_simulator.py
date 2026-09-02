"""Learner simulator: determinism, forgetting curve, learner-type divergence."""

import random

import pytest

from backend.learner_model.simulator import (
    LEARNER_TYPES,
    MAX_HALF_LIFE_DAYS,
    MIN_HALF_LIFE_DAYS,
    PRESETS,
    Interaction,
    MemoryState,
    SimulatedLearner,
    Simulator,
    expanding_schedule,
    fixed_schedule,
    recall_accuracy,
)

WORDS = list(range(1, 9))


def _logs(learner_type: str, seed: int, **kw):
    return SimulatedLearner.of_type(learner_type, seed=seed).generate_logs(
        WORDS, reviews_per_word=12, **kw
    )


def test_fixed_seed_gives_identical_logs():
    a = _logs("average", seed=7)
    b = _logs("average", seed=7)
    assert a == b
    assert _logs("average", seed=8) != a  # a different seed diverges


def test_first_exposure_is_recorded_and_always_correct():
    rows = _logs("forgetful", seed=1)
    firsts = [r for r in rows if r.review_index == 0]
    assert len(firsts) == len(WORDS)
    assert all(r.correct and r.elapsed_days == 0.0 and r.p_recall == 1.0 for r in firsts)


def test_true_recall_prob_falls_with_elapsed_time():
    sim = Simulator(PRESETS["average"])
    state = MemoryState(half_life_days=4.0)
    ps = [sim.true_recall_prob(state, d) for d in (0, 2, 4, 8, 16)]
    assert ps == sorted(ps, reverse=True)
    assert sim.true_recall_prob(state, 4.0) == pytest.approx(0.5, abs=1e-9)  # one half-life


def test_response_times_within_bounds():
    rows = _logs("average", seed=3)
    assert all(300 <= r.response_time_ms <= 30_000 for r in rows)


def test_half_life_stays_in_range_over_many_reviews():
    sim = Simulator(PRESETS["fast"])
    rng = random.Random(0)
    state = sim.initial_state()
    for i in range(200):
        _c, _rt, _p, state = sim.review(state, 3.0, rng, first=(i == 0))
        assert MIN_HALF_LIFE_DAYS <= state.half_life_days <= MAX_HALF_LIFE_DAYS


def test_learner_types_diverge_in_retention():
    # Same words, schedule and seed -> retention fast > average > forgetful.
    sched = fixed_schedule(3.0)
    acc = {
        t: recall_accuracy(
            SimulatedLearner.of_type(t, seed=42).generate_logs(
                list(range(1, 41)), reviews_per_word=15, schedule=sched
            )
        )
        for t in LEARNER_TYPES
    }
    assert acc["fast"] > acc["average"] > acc["forgetful"]
    assert acc["fast"] - acc["forgetful"] > 0.1  # a *visible* gap


def test_lapse_resets_streak_and_bumps_lapses():
    sim = Simulator(PRESETS["forgetful"])
    state = MemoryState(half_life_days=30.0, reviews=5, lapses=0, streak=5)
    # a long gap vs a 30-day half-life -> very likely a miss
    rng = random.Random(0)
    correct, _rt, _p, new = sim.review(state, 120.0, rng)
    assert correct is False
    assert new.streak == 0 and new.lapses == 1
    assert new.half_life_days < state.half_life_days


def test_expanding_schedule_grows_then_collapses():
    sched = expanding_schedule(base_days=1.0)
    assert sched(MemoryState(streak=1), 1) == 1.0
    assert sched(MemoryState(streak=2), 2) == 2.0
    assert sched(MemoryState(streak=4), 4) == 8.0
    assert sched(MemoryState(streak=0), 9) == 1.0  # after a lapse


def test_logs_are_time_ordered_and_shaped():
    rows = _logs("average", seed=5)
    assert rows == sorted(rows, key=lambda r: (r.t_days, r.word_id, r.review_index))
    r = rows[0]
    assert isinstance(r, Interaction)
    assert set(vars(r)) == {
        "word_id",
        "review_index",
        "t_days",
        "elapsed_days",
        "correct",
        "response_time_ms",
        "p_recall",
    }


def test_every_type_has_a_preset():
    assert set(LEARNER_TYPES) == set(PRESETS)
