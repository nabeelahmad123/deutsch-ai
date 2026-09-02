"""Synthetic learner simulator (CLAUDE.md section 12).

Generates plausible (word_id, correct, response_time, elapsed_since_last_review)
interaction logs from parameterised forgetting curves. Learner types: "fast",
"average", "forgetful" -- differing in memory-decay rate and noise.

Day-1 status: stub. Full implementation is build-order step 7.
"""

from __future__ import annotations

from dataclasses import dataclass

LEARNER_TYPES = ("fast", "average", "forgetful")


@dataclass(frozen=True)
class LearnerParams:
    decay_rate: float  # per-day exponential forgetting rate
    noise: float  # std of logit noise on recall outcome
    learning_gain: float  # half-life multiplier per successful recall
    base_response_ms: int


PRESETS: dict[str, LearnerParams] = {
    "fast": LearnerParams(decay_rate=0.05, noise=0.3, learning_gain=2.2, base_response_ms=1200),
    "average": LearnerParams(decay_rate=0.12, noise=0.5, learning_gain=1.8, base_response_ms=1800),
    "forgetful": LearnerParams(
        decay_rate=0.30, noise=0.7, learning_gain=1.4, base_response_ms=2600
    ),
}


@dataclass
class SimulatedLearner:
    params: LearnerParams
    seed: int = 0

    def simulate(self, n_days: int, reviews_per_day: int) -> list[dict]:
        raise NotImplementedError("simulator lands in build-order step 7")
