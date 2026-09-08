"""Synthetic learner simulator.

A parameterised forgetting-curve model. For a word with memory half-life ``h``
(days) reviewed after ``elapsed`` days, the learner's true recall probability is

    p = 2 ** (-elapsed / h)

perturbed by logistic noise. A successful review consolidates the memory
(``h`` grows by ``learning_gain``, minus the fraction ``decay_rate`` of that
gain that this learner fails to retain); a lapse resets ``h``.

Three learner types -- fast / average / forgetful -- differ in ``decay_rate``,
``noise`` and ``learning_gain``, so they visibly diverge in retention.

``Simulator.review`` is the primitive the offline evaluation drives with
SM-2 / HLR-chosen intervals; ``generate_logs`` produces standalone interaction
logs on the simulator's own expanding schedule. Plain Python + a seeded
``random.Random`` -- fully deterministic. No DB, no LLM.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

LEARNER_TYPES = ("fast", "average", "forgetful")

INITIAL_HALF_LIFE_DAYS = 1.0
MIN_HALF_LIFE_DAYS = 15.0 / (24 * 60)  # 15 minutes
MAX_HALF_LIFE_DAYS = 365.0
_MIN_RT_MS, _MAX_RT_MS = 300, 30_000


@dataclass(frozen=True)
class LearnerParams:
    decay_rate: float  # fraction of each review's potential gain this learner loses
    noise: float  # std of logistic noise added to the recall logit
    learning_gain: float  # half-life multiplier a perfectly-retaining learner would get
    base_response_ms: int


PRESETS: dict[str, LearnerParams] = {
    "fast": LearnerParams(decay_rate=0.05, noise=0.30, learning_gain=2.2, base_response_ms=1200),
    "average": LearnerParams(decay_rate=0.12, noise=0.50, learning_gain=1.8, base_response_ms=1800),
    "forgetful": LearnerParams(
        decay_rate=0.30, noise=0.70, learning_gain=1.4, base_response_ms=2600
    ),
}


@dataclass(frozen=True)
class MemoryState:
    half_life_days: float = INITIAL_HALF_LIFE_DAYS
    reviews: int = 0
    lapses: int = 0
    streak: int = 0  # consecutive successes since the last lapse


@dataclass
class Interaction:
    word_id: int
    review_index: int  # 0-based, per word (0 = first exposure)
    t_days: float  # cumulative time since this word's first exposure
    elapsed_days: float  # since this word's previous review (0.0 for the first)
    correct: bool
    response_time_ms: int
    p_recall: float  # the model's *true* recall probability (for calibration eval)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


class Simulator:
    """A single synthetic learner. Stateless across words; ``review`` takes and
    returns the per-word ``MemoryState``."""

    def __init__(self, params: LearnerParams) -> None:
        self.params = params

    def initial_state(self) -> MemoryState:
        return MemoryState()

    def true_recall_prob(self, state: MemoryState, elapsed_days: float) -> float:
        return _clamp(2.0 ** (-max(0.0, elapsed_days) / state.half_life_days), 1e-6, 1.0)

    def _noisy_prob(self, p: float, rng: random.Random) -> float:
        logit = math.log(p / (1.0 - p)) + rng.gauss(0.0, self.params.noise)
        return 1.0 / (1.0 + math.exp(-logit))

    def _response_time_ms(self, p_noisy: float, correct: bool, rng: random.Random) -> int:
        # Slower when the learner is unsure; slower still on a miss.
        factor = 1.0 + 1.6 * (1.0 - p_noisy) + (0.0 if correct else 0.8)
        jitter = math.exp(rng.gauss(0.0, 0.22))
        return int(_clamp(self.params.base_response_ms * factor * jitter, _MIN_RT_MS, _MAX_RT_MS))

    def _consolidate(self, half_life: float) -> float:
        gained = half_life * self.params.learning_gain
        kept = half_life + (gained - half_life) * (1.0 - self.params.decay_rate)
        return _clamp(kept, MIN_HALF_LIFE_DAYS, MAX_HALF_LIFE_DAYS)

    def review(
        self, state: MemoryState, elapsed_days: float, rng: random.Random, *, first: bool = False
    ) -> tuple[bool, int, float, MemoryState]:
        """Simulate one review. Returns (correct, response_time_ms, true_p, new_state).

        ``first=True`` marks an initial exposure: recall is not tested, the memory
        just starts consolidating.
        """
        if first:
            new = MemoryState(
                half_life_days=self._consolidate(state.half_life_days),
                reviews=state.reviews + 1,
                lapses=state.lapses,
                streak=1,
            )
            return True, self.params.base_response_ms, 1.0, new

        true_p = self.true_recall_prob(state, elapsed_days)
        p_noisy = self._noisy_prob(true_p, rng)
        correct = rng.random() < p_noisy
        rt = self._response_time_ms(p_noisy, correct, rng)

        if correct:
            new = MemoryState(
                half_life_days=self._consolidate(state.half_life_days),
                reviews=state.reviews + 1,
                lapses=state.lapses,
                streak=state.streak + 1,
            )
        else:
            new = MemoryState(
                half_life_days=INITIAL_HALF_LIFE_DAYS,
                reviews=state.reviews + 1,
                lapses=state.lapses + 1,
                streak=0,
            )
        return correct, rt, true_p, new


# --- schedules -------------------------------------------------------------

Schedule = Callable[[MemoryState, int], float]


def expanding_schedule(base_days: float = 1.0, cap_days: float = 90.0) -> Schedule:
    """Spaced-repetition-ish: the interval doubles with each success since the
    last lapse, and collapses back to ``base_days`` after a miss."""

    def next_interval(state: MemoryState, _review_index: int) -> float:
        return min(base_days * (2 ** max(0, state.streak - 1)), cap_days)

    return next_interval


def fixed_schedule(days: float) -> Schedule:
    def next_interval(_state: MemoryState, _review_index: int) -> float:
        return days

    return next_interval


# --- standalone log generation -----------------------------------------


@dataclass
class SimulatedLearner:
    params: LearnerParams
    seed: int = 0
    _sim: Simulator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sim = Simulator(self.params)

    @classmethod
    def of_type(cls, learner_type: str, seed: int = 0) -> SimulatedLearner:
        return cls(PRESETS[learner_type], seed=seed)

    def generate_logs(
        self,
        word_ids: list[int],
        *,
        reviews_per_word: int,
        schedule: Schedule | None = None,
        start_day: float = 0.0,
    ) -> list[Interaction]:
        """One interaction stream across ``word_ids``, time-ordered. Deterministic
        for a fixed ``seed``."""
        rng = random.Random(self.seed)
        schedule = schedule or expanding_schedule()
        rows: list[Interaction] = []

        for word_id in word_ids:
            state = self._sim.initial_state()
            t = start_day
            for i in range(reviews_per_word):
                elapsed = 0.0 if i == 0 else schedule(state, i)
                t += elapsed
                correct, rt, true_p, state = self._sim.review(state, elapsed, rng, first=(i == 0))
                rows.append(
                    Interaction(
                        word_id=word_id,
                        review_index=i,
                        t_days=round(t - start_day, 6),
                        elapsed_days=round(elapsed, 6),
                        correct=correct,
                        response_time_ms=rt,
                        p_recall=round(true_p, 6),
                    )
                )

        rows.sort(key=lambda r: (r.t_days, r.word_id, r.review_index))
        return rows


def recall_accuracy(interactions: list[Interaction]) -> float:
    """Fraction correct over the tested reviews (excludes first exposures)."""
    tested = [r for r in interactions if r.review_index > 0]
    return sum(r.correct for r in tested) / len(tested) if tested else 0.0
