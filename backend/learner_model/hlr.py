"""Half-Life Regression (Settles & Meeder, 2016).

Log-linear half-life:  log2(h_hat) = theta . x        (h_hat always > 0)
Recall probability:     p_hat = 2 ** (-lag_days / h_hat)

Per-instance loss (paper eq. 4, half-life term taken in log space for numerical
stability -- the raw half-life spans minutes to a year):

    L = (p_hat - p)^2  +  alpha * (log2 h_hat - log2 h_ref)^2  +  l2 * ||theta||^2

where ``p`` is the observed recall (1.0 / 0.0, clamped) and ``h_ref`` is the
half-life implied by that single outcome, ``h_ref = -lag / log2(p_clamped)``.

Features (""lag time, history of correct/incorrect, word
difficulty/frequency"): bias, sqrt(#prior correct), sqrt(#prior incorrect),
difficulty (normalised frequency rank, higher = rarer = harder). Full-batch
gradient descent -- deterministic, no RNG.

Reference: https://github.com/duolingo/halflife-regression
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import numpy as np

MIN_HALF_LIFE = 15.0 / (24 * 60)  # 15 minutes, in days
MAX_HALF_LIFE = 365.0  # 1 year, in days
FEATURE_NAMES = ("bias", "sqrt_correct", "sqrt_incorrect", "difficulty")
N_FEATURES = len(FEATURE_NAMES)

_LN2 = math.log(2.0)
_P_CLIP = 1e-4
_LOG2_MIN, _LOG2_MAX = math.log2(MIN_HALF_LIFE), math.log2(MAX_HALF_LIFE)


@dataclass(frozen=True)
class Instance:
    features: np.ndarray  # shape (N_FEATURES,)
    lag_days: float
    p_observed: float  # 1.0 or 0.0
    h_ref: float  # reference half-life for the regulariser


def _clip_ref(h: float) -> float:
    return float(np.clip(h, MIN_HALF_LIFE, MAX_HALF_LIFE))


def _h_ref(lag_days: float, p_observed: float) -> float:
    p = min(max(p_observed, _P_CLIP), 1.0 - _P_CLIP)
    return _clip_ref(-max(lag_days, 1e-6) / math.log2(p))


def make_features(n_correct: int, n_incorrect: int, difficulty: float) -> np.ndarray:
    return np.array(
        [1.0, math.sqrt(n_correct), math.sqrt(n_incorrect), float(difficulty)], dtype=float
    )


def to_instances(
    interactions: Iterable,
    *,
    difficulty: Callable[[int], float] | dict[int, float] | float = 0.5,
) -> list[Instance]:
    """Turn simulator ``Interaction``s into training instances.

    Groups by ``word_id``, walks each word's timeline in review order, and emits
    one instance per tested review (skips the first exposure). ``difficulty`` may
    be a constant, a ``{word_id: value}`` map, or a callable.
    """

    def diff_for(word_id: int) -> float:
        if callable(difficulty):
            return float(difficulty(word_id))
        if isinstance(difficulty, dict):
            return float(difficulty.get(word_id, 0.5))
        return float(difficulty)

    by_word: dict[int, list] = {}
    for row in interactions:
        by_word.setdefault(row.word_id, []).append(row)

    instances: list[Instance] = []
    for word_id, rows in by_word.items():
        rows = sorted(rows, key=lambda r: r.review_index)
        n_correct = n_incorrect = 0
        for row in rows:
            if row.review_index == 0:
                n_correct += 1  # first exposure: seen, "known"
                continue
            instances.append(
                Instance(
                    features=make_features(n_correct, n_incorrect, diff_for(word_id)),
                    lag_days=float(row.elapsed_days),
                    p_observed=1.0 if row.correct else 0.0,
                    h_ref=_h_ref(row.elapsed_days, 1.0 if row.correct else 0.0),
                )
            )
            if row.correct:
                n_correct += 1
            else:
                n_incorrect += 1
    return instances


@dataclass
class FitResult:
    losses: list[float] = field(default_factory=list)

    @property
    def final(self) -> float:
        return self.losses[-1] if self.losses else float("nan")


@dataclass
class HLRModel:
    weights: np.ndarray | None = None
    alpha: float = 0.01  # weight on the half-life regulariser
    l2: float = 1e-3
    learning_rate: float = 0.05

    # --- prediction ------------------------------------------------------
    def _log2_h(self, X: np.ndarray) -> np.ndarray:
        assert self.weights is not None, "call fit() first"
        return np.clip(X @ self.weights, _LOG2_MIN, _LOG2_MAX)

    def predict_half_life(self, X: np.ndarray) -> np.ndarray:
        return np.exp2(self._log2_h(np.atleast_2d(X)))

    def predict_recall(self, X: np.ndarray, lag_days) -> np.ndarray:
        h = self.predict_half_life(X)
        lag = np.asarray(lag_days, dtype=float)
        return np.clip(np.exp2(-lag / h), 0.0, 1.0)

    # --- training ------------------------------------------------------
    def _loss(self, X, lag, p, log2_href) -> float:
        log2_h = np.clip(X @ self.weights, _LOG2_MIN, _LOG2_MAX)
        h = np.exp2(log2_h)
        p_hat = np.clip(np.exp2(-lag / h), 1e-9, 1.0)
        recall = np.mean((p_hat - p) ** 2)
        href = self.alpha * np.mean((log2_h - log2_href) ** 2)
        reg = self.l2 * float(self.weights @ self.weights)
        return float(recall + href + reg)

    def fit(self, instances: list[Instance], *, iterations: int = 400) -> FitResult:
        if not instances:
            raise ValueError("no training instances")
        X = np.stack([i.features for i in instances])
        lag = np.array([i.lag_days for i in instances], dtype=float)
        p = np.clip(np.array([i.p_observed for i in instances]), _P_CLIP, 1 - _P_CLIP)
        log2_href = np.clip(np.log2(np.array([i.h_ref for i in instances])), _LOG2_MIN, _LOG2_MAX)
        if self.weights is None:
            self.weights = np.zeros(X.shape[1])

        result = FitResult()
        for _ in range(iterations):
            log2_h = np.clip(X @ self.weights, _LOG2_MIN, _LOG2_MAX)
            h = np.exp2(log2_h)
            p_hat = np.clip(np.exp2(-lag / h), 1e-9, 1.0)
            # d/d(log2_h) of each loss term, then chain through x:
            d_recall = 2.0 * (p_hat - p) * p_hat * (_LN2**2) * (lag / h)
            d_href = 2.0 * self.alpha * (log2_h - log2_href)
            grad = (X * (d_recall + d_href)[:, None]).mean(axis=0) + self.l2 * self.weights
            self.weights = self.weights - self.learning_rate * grad
            result.losses.append(self._loss(X, lag, p, log2_href))
        return result
