"""LG-18: the evaluation writeup -- real-data validation + markdown + figures."""

import json

from backend.learner_model.evaluate import run_evaluation
from backend.learner_model.real_data import collect_real_review_logs

_SMALL_EVAL = dict(n_learners=3, n_words=16, horizon_days=60.0, hlr_iterations=120)
_SMALL_REAL = dict(n_users=4, n_words=16, days=60, seed=0)


def test_real_review_logs_recall_matches_offline_sm2():
    """The section-17 check: the offline eval's SM-2 retention number matches
    what the real scheduler + real review_logs table produce."""
    real = collect_real_review_logs(**_SMALL_REAL)
    assert real["n_review_logs"] > 200
    assert 0.0 <= real["recall_accuracy"] <= 1.0

    eval_sm2 = run_evaluation(seed=0, **_SMALL_EVAL)["strategies"]["sm2"]["by_learner_type"][
        "average"
    ]["recall_accuracy"]
    assert abs(real["recall_accuracy"] - eval_sm2) < 0.08


def test_collect_real_review_logs_is_deterministic():
    a = collect_real_review_logs(**_SMALL_REAL)
    b = collect_real_review_logs(**_SMALL_REAL)
    assert a == b


def test_build_markdown_has_all_sections():
    from backend.learner_model.report import build_markdown

    result = run_evaluation(seed=0, include_raw=True, **_SMALL_EVAL)
    real = collect_real_review_logs(**_SMALL_REAL)
    md = build_markdown(result, real, [f"f{i}.png" for i in range(4)])

    assert md.startswith("# Evaluation")
    assert "| strategy | recall (retention)" in md
    assert "## Validation against real logged sessions" in md
    assert "real scheduler + real `review_logs`" in md
    for i in range(4):
        assert f"](f{i}.png)" in md
    assert "Δ = " in md


def test_figures_write_non_empty_pngs(tmp_path, monkeypatch):
    from backend.learner_model import report

    monkeypatch.setattr(report, "DOCS", tmp_path)
    result = run_evaluation(seed=0, include_raw=True, **_SMALL_EVAL)
    names = [
        report._fig_recall_over_time(result),
        report._fig_calibration_curve(result),
        report._fig_calibration_metrics(result),
        report._fig_efficiency(result),
    ]
    for n in names:
        assert (tmp_path / n).stat().st_size > 1000  # a real PNG


def test_include_raw_arrays_align():
    result = run_evaluation(seed=0, include_raw=True, **_SMALL_EVAL)
    raw = result["strategies"]["hlr"]["_raw"]
    assert len(raw["cal_p"]) == len(raw["cal_y"]) > 0
    assert len(raw["ret_t"]) == len(raw["ret_y"]) > 0
    assert all(0.0 <= p <= 1.0 for p in raw["cal_p"])


def test_run_evaluation_json_excludes_raw_by_default():
    result = run_evaluation(seed=0, **_SMALL_EVAL)
    assert "_raw" not in result["strategies"]["hlr"]
    json.dumps(result)  # still serialisable
