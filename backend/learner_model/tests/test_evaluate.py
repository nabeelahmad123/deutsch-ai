"""The offline evaluation harness (LG-17 AC: one command -> a metrics dict)."""

import json

from backend.learner_model.evaluate import STRATEGIES, run_evaluation

SMALL = dict(n_learners=2, n_words=8, horizon_days=45.0, hlr_iterations=150)


def test_run_evaluation_shape():
    result = run_evaluation(seed=0, **SMALL)

    assert set(result) == {"config", "hlr", "strategies"}
    assert set(result["strategies"]) == set(STRATEGIES)
    assert set(result["hlr"]) == {"weights", "train_loss_start", "train_loss_final"}

    for name in STRATEGIES:
        s = result["strategies"][name]
        assert set(s) == {"retention", "calibration", "by_learner_type"}
        ret = s["retention"]
        assert 0.0 <= ret["recall_accuracy"] <= 1.0
        assert 0.0 <= ret["review_efficiency"] <= 1.0
        assert ret["reviews"] > 0
        assert set(s["by_learner_type"]) == {"fast", "average", "forgetful"}
        cal = s["calibration"]
        assert 0.0 <= cal["brier_score"] <= 1.0
        assert cal["log_loss"] >= 0.0
        assert cal["roc_auc"] is None or 0.0 <= cal["roc_auc"] <= 1.0


def test_result_is_json_serialisable():
    json.dumps(run_evaluation(seed=1, **SMALL))  # must not raise


def test_deterministic_for_a_seed():
    a = run_evaluation(seed=3, **SMALL)
    b = run_evaluation(seed=3, **SMALL)
    assert a == b
    assert run_evaluation(seed=4, **SMALL) != a


def test_hlr_training_loss_decreases():
    hlr = run_evaluation(seed=0, **SMALL)["hlr"]
    assert hlr["train_loss_final"] < hlr["train_loss_start"]


def test_hlr_and_sm2_beat_the_random_baseline_on_retention():
    r = run_evaluation(seed=0, **SMALL)["strategies"]
    rand = r["random"]["retention"]["recall_accuracy"]
    assert r["sm2"]["retention"]["recall_accuracy"] > rand
    assert r["hlr"]["retention"]["recall_accuracy"] > rand
    # random has no recall model -> chance-level calibration
    assert r["random"]["calibration"]["roc_auc"] in (0.5, None)


def test_recall_over_time_buckets_present():
    ret = run_evaluation(seed=0, **SMALL)["strategies"]["hlr"]["retention"]
    assert list(ret["recall_over_time"]) == [
        "0-15d",
        "15-30d",
        "30-45d",
        "45-60d",
        "60-75d",
        "75-90d",
    ]
