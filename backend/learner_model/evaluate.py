"""Offline evaluation harness (CLAUDE.md section 12).

Compares three scheduling strategies -- random / SM-2 / HLR -- on the learner
simulator, along two independent axes:

  RETENTION (each strategy runs its own schedule):
    - recall accuracy, overall and bucketed over simulated time
    - review efficiency: retained cards per review issued

  CALIBRATION (all strategies scored on the SAME probe schedule of varied
  intervals, so their recall *model* is measured apart from their schedule):
    - Brier score, log-loss, ROC AUC of predicted vs. actual recall

The HLR model is trained once on logs from a held-out learner population, then
frozen. Deterministic given ``seed``.

    python -m backend.learner_model.evaluate        # prints the metrics dict

Plots + docs/EVALUATION.md are LG-18.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from backend.learner_model import metrics
from backend.learner_model.hlr import HLRModel, to_instances
from backend.learner_model.simulator import (
    LEARNER_TYPES,
    PRESETS,
    SimulatedLearner,
    Simulator,
    expanding_schedule,
    fixed_schedule,
)
from backend.learner_model.strategies import HLRStrategy, RandomStrategy, SM2Strategy

TIME_BUCKETS = [0, 15, 30, 45, 60, 75, 90]
STRATEGIES = ("random", "sm2", "hlr")


@dataclass
class Trial:
    p_pred: list[float] = field(default_factory=list)
    correct: list[int] = field(default_factory=list)
    t_days: list[float] = field(default_factory=list)
    reviews: int = 0
    retained: int = 0  # cards whose final observed review was correct
    cards: int = 0


def _make_strategy(name: str, rng: random.Random, difficulty: float):
    if name == "random":
        return RandomStrategy(rng=rng)
    if name == "sm2":
        return SM2Strategy()
    return HLRStrategy(model=_TRAINED[name], difficulty=difficulty)


_TRAINED: dict[str, HLRModel] = {}


def _run_card(
    strategy,
    sim: Simulator,
    rng: random.Random,
    *,
    horizon: float,
    trial: Trial,
    probe: RandomStrategy | None = None,
) -> None:
    """One card. If ``probe`` is given, review intervals come from it (calibration
    mode); otherwise from ``strategy`` (retention mode)."""
    ss = strategy.initial_state()
    ms = sim.initial_state()
    _c, _rt, _p, ms = sim.review(ms, 0.0, rng, first=True)
    probe_state = probe.initial_state() if probe else None
    t = 0.0
    last_correct: bool | None = None
    while True:
        elapsed = (
            probe.next_interval_days(probe_state) if probe else strategy.next_interval_days(ss)
        )
        if t + elapsed > horizon:
            break
        t += elapsed
        p_pred = strategy.predict_recall(ss, elapsed)
        correct, _rt, _true_p, ms = sim.review(ms, elapsed, rng)
        trial.p_pred.append(p_pred)
        trial.correct.append(int(correct))
        trial.t_days.append(t)
        trial.reviews += 1
        last_correct = correct
        ss = strategy.update(ss, elapsed, correct)
        if probe:
            probe_state = probe.update(probe_state, elapsed, correct)
    trial.cards += 1
    if last_correct:
        trial.retained += 1


def _metrics(trial: Trial, *, retention: bool) -> dict:
    out: dict = {
        "n_observations": len(trial.correct),
        "reviews": trial.reviews,
    }
    if retention:
        out["recall_accuracy"] = round(metrics.recall_accuracy(trial.correct), 4)
        out["review_efficiency"] = (
            round(trial.retained / trial.reviews, 4) if trial.reviews else 0.0
        )
        out["retained_cards"] = f"{trial.retained}/{trial.cards}"
        out["recall_over_time"] = {
            k: (round(v, 3) if v == v else None)
            for k, v in metrics.bucketed_accuracy(
                trial.t_days, trial.correct, edges=TIME_BUCKETS
            ).items()
        }
    else:
        out["brier_score"] = round(metrics.brier_score(trial.p_pred, trial.correct), 4)
        out["log_loss"] = round(metrics.log_loss(trial.p_pred, trial.correct), 4)
        auc = metrics.roc_auc(trial.p_pred, trial.correct)
        out["roc_auc"] = round(auc, 4) if auc == auc else None
        out["observed_recall"] = round(metrics.recall_accuracy(trial.correct), 4)
    return out


def _train_hlr(
    word_ids: list[int], difficulty: dict[int, float], *, iterations: int
) -> tuple[HLRModel, dict]:
    logs = []
    for k in range(6):
        logs += SimulatedLearner.of_type("average", seed=1000 + k).generate_logs(
            word_ids, reviews_per_word=14, schedule=expanding_schedule()
        )
        logs += SimulatedLearner.of_type("average", seed=2000 + k).generate_logs(
            word_ids, reviews_per_word=14, schedule=fixed_schedule(3.0)  # more lapses -> signal
        )
    model = HLRModel(learning_rate=0.08)
    fit = model.fit(to_instances(logs, difficulty=difficulty), iterations=iterations)
    return model, {
        "weights": {
            n: round(float(w), 4)
            for n, w in zip(
                ("bias", "sqrt_correct", "sqrt_incorrect", "difficulty"), model.weights, strict=True
            )
        },
        "train_loss_start": round(fit.losses[0], 4),
        "train_loss_final": round(fit.final, 4),
    }


def run_evaluation(
    *,
    n_learners: int = 8,
    n_words: int = 40,
    horizon_days: float = 90.0,
    seed: int = 0,
    hlr_iterations: int = 600,
) -> dict:
    word_ids = list(range(1, n_words + 1))
    difficulty = {w: round(w / (n_words + 1), 3) for w in word_ids}

    model, hlr_info = _train_hlr(word_ids, difficulty, iterations=hlr_iterations)
    _TRAINED["hlr"] = model

    def merged(trials: list[Trial]) -> Trial:
        m = Trial()
        for tr in trials:
            m.p_pred += tr.p_pred
            m.correct += tr.correct
            m.t_days += tr.t_days
            m.reviews += tr.reviews
            m.retained += tr.retained
            m.cards += tr.cards
        return m

    results: dict[str, dict] = {}
    for name in STRATEGIES:
        retention_trials: list[Trial] = []
        calibration = Trial()
        by_type: dict[str, dict] = {}
        for learner_type in LEARNER_TYPES:
            type_retention = Trial()
            sim = Simulator(PRESETS[learner_type])
            for li in range(n_learners):
                for w in word_ids:
                    key = (seed, name, learner_type, li, w)
                    _run_card(
                        _make_strategy(name, random.Random(hash((*key, "s1"))), difficulty[w]),
                        sim,
                        random.Random(hash((*key, "r1"))),
                        horizon=horizon_days,
                        trial=type_retention,
                    )
                    _run_card(
                        _make_strategy(name, random.Random(hash((*key, "s2"))), difficulty[w]),
                        sim,
                        random.Random(hash((*key, "r2"))),
                        horizon=horizon_days,
                        trial=calibration,
                        probe=RandomStrategy(
                            rng=random.Random(hash((seed, learner_type, li, w, "probe"))),
                            min_days=0.5,
                            max_days=10.0,
                        ),
                    )
            by_type[learner_type] = _metrics(type_retention, retention=True)
            retention_trials.append(type_retention)
        results[name] = {
            "retention": _metrics(merged(retention_trials), retention=True),
            "calibration": _metrics(calibration, retention=False),
            "by_learner_type": by_type,
        }

    return {
        "config": {
            "n_learners": n_learners,
            "n_words": n_words,
            "horizon_days": horizon_days,
            "seed": seed,
            "time_buckets": TIME_BUCKETS,
        },
        "hlr": hlr_info,
        "strategies": results,
    }


def main() -> None:
    print(json.dumps(run_evaluation(), indent=2))


if __name__ == "__main__":
    main()
