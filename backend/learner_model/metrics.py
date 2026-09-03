"""Calibration + retention metrics for the offline evaluation (section 12).

All take equal-length arrays of predicted recall probabilities and observed
0/1 outcomes. Pure NumPy, no sklearn.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-12


def _arrays(p_pred, y_true) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(p_pred, dtype=float)
    y = np.asarray(y_true, dtype=float)
    if p.shape != y.shape:
        raise ValueError(f"shape mismatch: {p.shape} vs {y.shape}")
    return p, y


def brier_score(p_pred, y_true) -> float:
    """Mean squared error between predicted probability and outcome (lower better)."""
    p, y = _arrays(p_pred, y_true)
    return float(np.mean((p - y) ** 2)) if p.size else float("nan")


def log_loss(p_pred, y_true) -> float:
    """Binary cross-entropy (lower better)."""
    p, y = _arrays(p_pred, y_true)
    p = np.clip(p, _EPS, 1.0 - _EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if p.size else float("nan")


def roc_auc(p_pred, y_true) -> float:
    """Rank-based ROC AUC (Mann-Whitney U). NaN if only one class is present."""
    p, y = _arrays(p_pred, y_true)
    pos = p[y == 1]
    neg = p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, p.size + 1)
    # average ranks for ties
    _, inv, counts = np.unique(p, return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    start = cum - counts
    avg = (start + cum + 1) / 2.0
    ranks = avg[inv]
    rank_sum_pos = ranks[y == 1].sum()
    auc = (rank_sum_pos - pos.size * (pos.size + 1) / 2.0) / (pos.size * neg.size)
    return float(auc)


def recall_accuracy(y_true) -> float:
    y = np.asarray(y_true, dtype=float)
    return float(np.mean(y)) if y.size else float("nan")


def bucketed_accuracy(t_days, y_true, *, edges: list[float]) -> dict[str, float]:
    """Mean outcome within each [edges[i], edges[i+1]) time bucket."""
    t = np.asarray(t_days, dtype=float)
    y = np.asarray(y_true, dtype=float)
    out: dict[str, float] = {}
    for lo, hi in zip(edges, edges[1:], strict=False):  # consecutive pairs
        mask = (t >= lo) & (t < hi)
        out[f"{lo:g}-{hi:g}d"] = float(np.mean(y[mask])) if mask.any() else float("nan")
    return out
