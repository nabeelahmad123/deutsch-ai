"""Half-Life Regression: features, training convergence, prediction bounds."""

import numpy as np
import pytest

from backend.learner_model.hlr import (
    FEATURE_NAMES,
    MAX_HALF_LIFE,
    MIN_HALF_LIFE,
    N_FEATURES,
    HLRModel,
    Instance,
    make_features,
    to_instances,
)
from backend.learner_model.simulator import SimulatedLearner, fixed_schedule


def _training_logs(learner_type="average", seed=0, words=40, reviews=15):
    return SimulatedLearner.of_type(learner_type, seed=seed).generate_logs(
        list(range(1, words + 1)), reviews_per_word=reviews, schedule=fixed_schedule(2.0)
    )


def test_make_features_shape_and_content():
    x = make_features(n_correct=9, n_incorrect=4, difficulty=0.7)
    assert x.shape == (N_FEATURES,)
    assert list(FEATURE_NAMES) == ["bias", "sqrt_correct", "sqrt_incorrect", "difficulty"]
    assert x[0] == 1.0 and x[1] == 3.0 and x[2] == 2.0 and x[3] == 0.7


def test_to_instances_walks_history_and_skips_first_exposure():
    logs = _training_logs(words=3, reviews=5)
    inst = to_instances(logs, difficulty=lambda wid: wid / 100)
    # 3 words x (5 - 1 tested reviews)
    assert len(inst) == 3 * 4
    assert all(i.features.shape == (N_FEATURES,) for i in inst)
    assert all(i.p_observed in (0.0, 1.0) for i in inst)
    assert all(MIN_HALF_LIFE <= i.h_ref <= MAX_HALF_LIFE for i in inst)
    # prior-correct count is non-decreasing within a word's instances
    first_word = [i for i in inst][:4]
    assert [i.features[1] for i in first_word] == sorted(i.features[1] for i in first_word)


def test_fit_reduces_loss_and_is_deterministic():
    inst = to_instances(_training_logs(), difficulty=0.5)
    r1 = HLRModel().fit(inst, iterations=300)
    r2 = HLRModel().fit(inst, iterations=300)
    assert r1.losses == r2.losses  # full-batch GD, no RNG
    assert r1.losses[-1] < r1.losses[0]
    assert r1.losses[-1] < 0.9 * r1.losses[0]  # a meaningful drop
    # monotone-ish: last 50 iters never increase
    tail = r1.losses[-50:]
    assert all(b <= a + 1e-9 for a, b in zip(tail, tail[1:], strict=False))


def test_predictions_respect_bounds():
    model = HLRModel()
    model.fit(to_instances(_training_logs(), difficulty=0.5), iterations=200)

    X = np.array([make_features(c, i, d) for c in (0, 5, 20) for i in (0, 3) for d in (0.1, 0.9)])
    h = model.predict_half_life(X)
    assert np.all(h >= MIN_HALF_LIFE - 1e-9) and np.all(h <= MAX_HALF_LIFE + 1e-9)

    p = model.predict_recall(X, lag_days=np.full(len(X), 3.0))
    assert np.all((p >= 0.0) & (p <= 1.0))
    # longer lag -> lower predicted recall for the same features
    p_short = model.predict_recall(X, lag_days=np.full(len(X), 1.0))
    p_long = model.predict_recall(X, lag_days=np.full(len(X), 30.0))
    assert np.all(p_long <= p_short + 1e-9)


def test_more_prior_correct_predicts_longer_half_life():
    model = HLRModel()
    model.fit(to_instances(_training_logs("fast", seed=1), difficulty=0.5), iterations=400)
    weak = model.predict_half_life(make_features(1, 3, 0.5))[0]
    strong = model.predict_half_life(make_features(20, 0, 0.5))[0]
    assert strong > weak


def test_beats_a_constant_recall_baseline_on_held_out_logs():
    train = to_instances(_training_logs("average", seed=0), difficulty=0.5)
    test = to_instances(_training_logs("average", seed=999), difficulty=0.5)
    model = HLRModel()
    model.fit(train, iterations=500)

    X = np.stack([i.features for i in test])
    lag = np.array([i.lag_days for i in test])
    y = np.array([i.p_observed for i in test])
    p_hat = model.predict_recall(X, lag)
    mse_model = float(np.mean((p_hat - y) ** 2))
    mse_const = float(np.mean((y.mean() - y) ** 2))
    assert mse_model < mse_const


def test_fit_rejects_empty():
    with pytest.raises(ValueError):
        HLRModel().fit([])


def test_instance_is_frozen():
    inst = Instance(features=make_features(1, 1, 0.5), lag_days=2.0, p_observed=1.0, h_ref=5.0)
    with pytest.raises(AttributeError):  # frozen dataclass
        inst.lag_days = 3.0
