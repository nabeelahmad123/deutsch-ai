"""Scheduling strategies for the offline evaluation.

Each strategy, per card, decides the next review interval and predicts the
recall probability at review time; ``update`` folds in the observed outcome.
Three of them:

  random  -- a naive baseline: uniform intervals, no learning.
  sm2     -- the deterministic SM-2 core (backend.core.scheduler).
  hlr     -- a pre-trained Half-Life Regression model.

Deterministic given the RNGs passed in.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from backend.core.scheduler import (
    INITIAL_EASE_FACTOR,
    CardState,
    quality_from_response,
    sm2_update,
)
from backend.learner_model.hlr import HLRModel, make_features

_TARGET_RETENTION = 0.75  # review a card when predicted recall drops to this
_NEUTRAL_RT_MS = 3000


def _interval_for_retention(half_life_days: float, target: float = _TARGET_RETENTION) -> float:
    # p = 2**(-t/h)  ->  t = h * -log2(p)
    return max(0.1, half_life_days * -math.log2(target))


# --- random baseline ----------------------------------------------------


@dataclass
class RandomState:
    reviews: int = 0


@dataclass
class RandomStrategy:
    rng: random.Random
    min_days: float = 1.0
    max_days: float = 30.0
    name: str = "random"

    def initial_state(self) -> RandomState:
        return RandomState()

    def next_interval_days(self, _state: RandomState) -> float:
        return self.rng.uniform(self.min_days, self.max_days)

    def predict_recall(self, _state: RandomState, _elapsed_days: float) -> float:
        return 0.5  # no model

    def update(self, state: RandomState, _elapsed_days: float, _correct: bool) -> RandomState:
        return RandomState(reviews=state.reviews + 1)


# --- SM-2 ------------------------------------------------------------


@dataclass
class SM2Strategy:
    name: str = "sm2"

    def initial_state(self) -> CardState:
        return CardState(repetitions=1, ease_factor=INITIAL_EASE_FACTOR, interval_days=1)

    def next_interval_days(self, state: CardState) -> float:
        return float(max(1, state.interval_days))

    def predict_recall(self, state: CardState, elapsed_days: float) -> float:
        # SM-2 has no probability; read its interval as a half-life proxy.
        h = max(1.0, float(state.interval_days))
        return float(2.0 ** (-elapsed_days / h))

    def update(self, state: CardState, _elapsed_days: float, correct: bool) -> CardState:
        quality = quality_from_response(correct, _NEUTRAL_RT_MS)
        return sm2_update(state, quality)


# --- HLR ------------------------------------------------------------


@dataclass
class HLRState:
    n_correct: int = 0
    n_incorrect: int = 0


@dataclass
class HLRStrategy:
    model: HLRModel
    difficulty: float = 0.5
    name: str = "hlr"
    _last_half_life: float = field(default=1.0, repr=False)

    def initial_state(self) -> HLRState:
        return HLRState()

    def _half_life(self, state: HLRState) -> float:
        x = make_features(state.n_correct, state.n_incorrect, self.difficulty)
        return float(self.model.predict_half_life(x)[0])

    def next_interval_days(self, state: HLRState) -> float:
        self._last_half_life = self._half_life(state)
        return _interval_for_retention(self._last_half_life)

    def predict_recall(self, state: HLRState, elapsed_days: float) -> float:
        x = make_features(state.n_correct, state.n_incorrect, self.difficulty)
        return float(self.model.predict_recall(x, elapsed_days)[0])

    def update(self, state: HLRState, _elapsed_days: float, correct: bool) -> HLRState:
        return HLRState(
            n_correct=state.n_correct + (1 if correct else 0),
            n_incorrect=state.n_incorrect + (0 if correct else 1),
        )
