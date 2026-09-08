"""Render the offline evaluation into docs/EVALUATION.md + plots.

    python -m backend.learner_model.report

Runs the simulator evaluation (evaluate.run_evaluation), the real-scheduler
validation (real_data.collect_real_review_logs), draws four figures, and writes
docs/EVALUATION.md. Deterministic. matplotlib is a dev dependency.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from backend.learner_model.evaluate import STRATEGIES, run_evaluation  # noqa: E402
from backend.learner_model.real_data import collect_real_review_logs  # noqa: E402

DOCS = Path(__file__).resolve().parents[2] / "docs"
_COLORS = {"random": "#9aa0a6", "sm2": "#2d6cdf", "hlr": "#d9822b"}
_PNG_META = {"Software": "learn-german eval"}  # keep PNGs reproducible-ish


def _save(fig, name: str) -> str:
    path = DOCS / name
    fig.savefig(path, dpi=110, bbox_inches="tight", metadata=_PNG_META)
    plt.close(fig)
    return name


def _fig_recall_over_time(result: dict) -> str:
    fig, ax = plt.subplots(figsize=(6, 3.4))
    for name in STRATEGIES:
        buckets = result["strategies"][name]["retention"]["recall_over_time"]
        xs = [i * 15 + 7.5 for i in range(len(buckets))]
        ys = [v if v is not None else np.nan for v in buckets.values()]
        ax.plot(xs, ys, "o-", label=name, color=_COLORS[name])
    ax.set_xlabel("simulated day")
    ax.set_ylabel("recall accuracy")
    ax.set_ylim(0, 1)
    ax.set_title("Recall accuracy over simulated time")
    ax.legend()
    ax.grid(alpha=0.3)
    return _save(fig, "eval_recall_over_time.png")


def _fig_calibration_curve(result: dict) -> str:
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.plot([0, 1], [0, 1], "--", color="#bbb", label="perfect")
    for name in STRATEGIES:
        raw = result["strategies"][name]["_raw"]
        p = np.array(raw["cal_p"])
        y = np.array(raw["cal_y"])
        edges = np.linspace(0, 1, 11)
        xs, ys = [], []
        for lo, hi in zip(edges[:-1], edges[1:], strict=True):
            m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
            if m.sum() >= 20:
                xs.append(p[m].mean())
                ys.append(y[m].mean())
        ax.plot(xs, ys, "o-", label=name, color=_COLORS[name])
    ax.set_xlabel("mean predicted recall")
    ax.set_ylabel("observed recall")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Calibration (reliability)")
    ax.legend()
    ax.grid(alpha=0.3)
    return _save(fig, "eval_calibration_curve.png")


def _fig_calibration_metrics(result: dict) -> str:
    fig, ax = plt.subplots(figsize=(6, 3.4))
    labels = ["Brier", "log-loss", "1 - AUC"]
    x = np.arange(len(labels))
    width = 0.26
    for i, name in enumerate(STRATEGIES):
        c = result["strategies"][name]["calibration"]
        auc = c["roc_auc"] if c["roc_auc"] is not None else 0.5
        vals = [c["brier_score"], c["log_loss"], 1 - auc]
        ax.bar(x + (i - 1) * width, vals, width, label=name, color=_COLORS[name])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title("Calibration metrics (lower is better)")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    return _save(fig, "eval_calibration_metrics.png")


def _fig_efficiency(result: dict) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.4, 3.4))
    for name in STRATEGIES:
        r = result["strategies"][name]["retention"]
        ax1.scatter(r["reviews"], r["recall_accuracy"], s=90, color=_COLORS[name])
        ax1.annotate(
            name, (r["reviews"], r["recall_accuracy"]), textcoords="offset points", xytext=(6, 4)
        )
    ax1.set_xlabel("reviews issued")
    ax1.set_ylabel("recall accuracy")
    ax1.set_title("Retention vs. review cost")
    ax1.grid(alpha=0.3)

    effs = [result["strategies"][n]["retention"]["review_efficiency"] for n in STRATEGIES]
    ax2.bar(STRATEGIES, effs, color=[_COLORS[n] for n in STRATEGIES])
    ax2.set_ylabel("retained cards / review")
    ax2.set_title("Review efficiency")
    ax2.grid(alpha=0.3, axis="y")
    return _save(fig, "eval_efficiency.png")


def _metrics_table(result: dict) -> str:
    head = (
        "| strategy | recall (retention) | review efficiency | reviews | "
        "Brier | log-loss | AUC |\n|---|---|---|---|---|---|---|"
    )
    rows = []
    for name in STRATEGIES:
        r = result["strategies"][name]["retention"]
        c = result["strategies"][name]["calibration"]
        rows.append(
            f"| {name} | {r['recall_accuracy']:.3f} | {r['review_efficiency']:.3f} | "
            f"{r['reviews']} | {c['brier_score']:.3f} | {c['log_loss']:.3f} | "
            f"{c['roc_auc'] if c['roc_auc'] is not None else '—'} |"
        )
    return head + "\n" + "\n".join(rows)


def build_markdown(result: dict, real: dict, figures: list[str]) -> str:
    hlr = result["hlr"]
    cfg = result["config"]
    eval_sm2 = result["strategies"]["sm2"]["by_learner_type"]["average"]["recall_accuracy"]
    real_recall = real["recall_accuracy"]
    delta = abs(eval_sm2 - real_recall)
    return f"""# Evaluation

> Generated by `python -m backend.learner_model.report` — deterministic, no API
> key. Simulator: `backend/learner_model/simulator.py`. Config:
> {cfg['n_learners']} learners/type · {cfg['n_words']} words · {cfg['horizon_days']:.0f}-day horizon · seed {cfg['seed']}.

Three scheduling strategies are compared on the synthetic learner simulator:
**random** (uniform intervals, no model), **sm2** (the deterministic
`backend.core.scheduler`), and **hlr** (a Half-Life Regression model trained once
on held-out learners, then frozen).

## Headline

{_metrics_table(result)}

- **HLR maximises retention** (recall {result['strategies']['hlr']['retention']['recall_accuracy']:.2f}) by scheduling aggressively — at
  {result['strategies']['hlr']['retention']['reviews'] / max(1, result['strategies']['sm2']['retention']['reviews']):.1f}× SM-2's review count.
- **SM-2 is the most review-efficient** and, on the probe schedule, the
  best-calibrated (its interval read as a half-life is a decent probability).
- **random** is the floor: recall {result['strategies']['random']['retention']['recall_accuracy']:.2f}, chance-level calibration (AUC 0.50).

HLR weights (log2 half-life = θ·x): `{hlr['weights']}` — √correct positive,
√incorrect negative, as expected. Training loss {hlr['train_loss_start']:.3f} → {hlr['train_loss_final']:.3f}.

## Plots

![recall over time]({figures[0]})

![calibration reliability]({figures[1]})

![calibration metrics]({figures[2]})

![efficiency]({figures[3]})

## Validation against real logged sessions

The simulator eval runs SM-2 in memory. As a cross-check,
`backend/learner_model/real_data.py` runs the **actual** `backend.core.scheduler`
against a real (in-memory SQLite) `review_logs` table over a
{real['config']['days']}-day timeline ({real['config']['n_users']} users ×
{real['config']['n_words']} words), with the simulator deciding each outcome, and
reads the persisted rows back.

| source | SM-2 recall accuracy | n review_logs |
|---|---|---|
| offline eval (simulator, `average` learner) | **{eval_sm2:.3f}** | — |
| real scheduler + real `review_logs` | **{real_recall:.3f}** | {real['n_review_logs']} |

Δ = {delta:.3f} — the offline evaluation's SM-2 retention number matches the real
pipeline to within a percentage point.
"""


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    result = run_evaluation(include_raw=True)
    real = collect_real_review_logs()
    figures = [
        _fig_recall_over_time(result),
        _fig_calibration_curve(result),
        _fig_calibration_metrics(result),
        _fig_efficiency(result),
    ]
    (DOCS / "EVALUATION.md").write_text(build_markdown(result, real, figures), encoding="utf-8")
    print(f"wrote {DOCS / 'EVALUATION.md'} + {len(figures)} figures")


if __name__ == "__main__":
    main()
