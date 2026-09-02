"""Smoke tests: the learner-model package imports and its presets are well-formed.

Real model/simulator/evaluation tests arrive with build-order step 7.
"""

from backend.learner_model.hlr import MAX_HALF_LIFE, MIN_HALF_LIFE
from backend.learner_model.simulator import LEARNER_TYPES, PRESETS


def test_half_life_bounds_ordered():
    assert 0 < MIN_HALF_LIFE < MAX_HALF_LIFE


def test_every_learner_type_has_a_preset():
    assert set(LEARNER_TYPES) == set(PRESETS)
    for params in PRESETS.values():
        assert params.decay_rate > 0
        assert params.base_response_ms > 0
