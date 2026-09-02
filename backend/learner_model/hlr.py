"""Half-Life Regression (Settles & Meeder, 2016).

Predicts memory half-life h from features (lag time, count of prior correct /
incorrect recalls, word difficulty/frequency). Recall probability is

    p = 2 ** (-delta / h)

where delta is time since last review. Training minimises squared error on p
plus an L2 term on the half-life, per the paper.

Day-1 status: stub. Full implementation + SM-2 comparison is build-order step 7.
Reference implementation target: https://github.com/duolingo/halflife-regression
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_HALF_LIFE = 15.0 / (24 * 60)  # 15 minutes, in days
MAX_HALF_LIFE = 274.0  # ~9 months, in days


@dataclass
class HLRModel:
    weights: np.ndarray | None = None
    bias: float = 0.0

    def predict_half_life(self, features: np.ndarray) -> np.ndarray:
        raise NotImplementedError("HLR lands in build-order step 7")

    def predict_recall(self, features: np.ndarray, delta_days: np.ndarray) -> np.ndarray:
        raise NotImplementedError("HLR lands in build-order step 7")

    def fit(self, features: np.ndarray, delta_days: np.ndarray, recalled: np.ndarray) -> HLRModel:
        raise NotImplementedError("HLR lands in build-order step 7")
