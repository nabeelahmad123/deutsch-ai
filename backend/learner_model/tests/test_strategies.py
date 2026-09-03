"""The three scheduling strategies: intervals, recall predictions, updates."""

import random

from backend.learner_model.hlr import HLRModel, to_instances
from backend.learner_model.simulator import SimulatedLearner, fixed_schedule
from backend.learner_model.strategies import HLRStrategy, RandomStrategy, SM2Strategy


def _trained_model():
    logs = SimulatedLearner.of_type("average", seed=0).generate_logs(
        list(range(1, 21)), reviews_per_word=12, schedule=fixed_schedule(2.0)
    )
    m = HLRModel()
    m.fit(to_instances(logs, difficulty=0.5), iterations=200)
    return m


def test_random_strategy_is_a_pure_baseline():
    s = RandomStrategy(rng=random.Random(0), min_days=1, max_days=30)
    st = s.initial_state()
    intervals = [s.next_interval_days(st) for _ in range(50)]
    assert all(1 <= d <= 30 for d in intervals)
    assert s.predict_recall(st, 5.0) == 0.5  # no model
    assert s.update(st, 5.0, True).reviews == 1


def test_random_strategy_is_seed_deterministic():
    a = RandomStrategy(rng=random.Random(7))
    b = RandomStrategy(rng=random.Random(7))
    st = a.initial_state()
    assert [a.next_interval_days(st) for _ in range(10)] == [
        b.next_interval_days(st) for _ in range(10)
    ]


def test_sm2_strategy_grows_interval_on_success():
    s = SM2Strategy()
    st = s.initial_state()
    assert s.next_interval_days(st) >= 1
    for _ in range(4):
        st = s.update(st, s.next_interval_days(st), correct=True)
    assert s.next_interval_days(st) > 6  # SM-2: 1 -> 6 -> round(6*EF) -> ...
    p = s.predict_recall(st, elapsed_days=st.interval_days)
    assert 0.0 <= p <= 1.0
    # a lapse collapses the interval
    st = s.update(st, 3.0, correct=False)
    assert s.next_interval_days(st) == 1


def test_hlr_strategy_uses_the_model():
    model = _trained_model()
    s = HLRStrategy(model=model, difficulty=0.5)
    st = s.initial_state()
    assert s.next_interval_days(st) > 0
    assert 0.0 <= s.predict_recall(st, 3.0) <= 1.0

    strong = HLRStrategy(model=model, difficulty=0.5)
    strong_state = strong.initial_state()
    for _ in range(10):
        strong_state = strong.update(strong_state, 3.0, correct=True)
    # more consolidation -> longer scheduled interval
    assert strong.next_interval_days(strong_state) > s.next_interval_days(st)


def test_hlr_update_tracks_history():
    s = HLRStrategy(model=_trained_model())
    st = s.initial_state()
    st = s.update(st, 2.0, True)
    st = s.update(st, 2.0, False)
    st = s.update(st, 2.0, True)
    assert (st.n_correct, st.n_incorrect) == (2, 1)
