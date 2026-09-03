"""Calibration + retention metric functions."""

import math

import pytest

from backend.learner_model.metrics import (
    brier_score,
    bucketed_accuracy,
    log_loss,
    recall_accuracy,
    roc_auc,
)


def test_brier_score():
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0  # perfect
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0  # worst
    assert brier_score([0.5, 0.5], [1, 0]) == 0.25


def test_log_loss():
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))
    assert log_loss([0.999999, 0.000001], [1, 0]) < 1e-4  # near-perfect


def test_roc_auc_ranking():
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5  # constant -> chance
    assert roc_auc([0.7, 0.3, 0.6, 0.4], [1, 0, 1, 0]) == 1.0


def test_roc_auc_single_class_is_nan():
    assert math.isnan(roc_auc([0.3, 0.6, 0.9], [1, 1, 1]))
    assert math.isnan(roc_auc([0.3, 0.6], [0, 0]))


def test_roc_auc_handles_ties_between_classes():
    # two of the same score, one pos one neg -> that pair contributes 0.5
    auc = roc_auc([0.5, 0.5, 0.1], [1, 0, 0])
    assert auc == pytest.approx(0.75)  # (1.0 for the clear pair + 0.5 for the tie) / 2


def test_recall_accuracy():
    assert recall_accuracy([1, 1, 0, 0]) == 0.5
    assert math.isnan(recall_accuracy([]))


def test_bucketed_accuracy():
    t = [1, 5, 12, 20, 40]
    y = [1, 0, 1, 0, 1]
    out = bucketed_accuracy(t, y, edges=[0, 10, 30, 60])
    assert out["0-10d"] == 0.5  # t=1,5 -> [1,0]
    assert out["10-30d"] == 0.5  # t=12,20 -> [1,0]
    assert out["30-60d"] == 1.0  # t=40 -> [1]


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        brier_score([0.5, 0.5], [1])
