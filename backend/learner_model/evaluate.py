"""Offline evaluation harness (CLAUDE.md section 12).

Runs SM-2 baseline vs. HLR vs. a naive/random baseline through the simulator and
produces, into docs/EVALUATION.md:
  - recall accuracy over simulated time
  - calibration of predicted vs. actual recall (Brier score, log-loss, AUC)
  - review efficiency (words retained per review issued)
  - plots for each

Day-1 status: stub. This is build-order step 7. Not Deep Knowledge Tracing, not
RL -- explicitly out of scope (section 16).
"""

from __future__ import annotations

STRATEGIES = ("random", "sm2", "hlr")


def run_evaluation(*, n_learners: int = 100, n_days: int = 60) -> dict:
    raise NotImplementedError("evaluate lands in build-order step 7")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("evaluate.py is not implemented yet (build-order step 7)")
