"""The recovery-rate report is produced from a scripted run and every
scenario is handled gracefully (never crashes or hangs)."""

from backend.agent.recovery import build_report, compute_metrics, render_report, scenarios


def test_report_summary_and_dispositions(seeded_db, tmp_path):
    metrics, outcomes, _ = build_report(trace_dir=tmp_path)

    assert metrics.scenarios == len(scenarios()) == 7
    # the hard requirement: never a silent hang or crash
    assert metrics.crashed == 0
    assert metrics.hung == 0
    assert metrics.graceful_handling_rate == 1.0
    assert 0.0 <= metrics.recovery_rate <= 1.0
    assert 0.0 <= metrics.tool_call_success_rate <= 1.0
    assert metrics.faults_injected >= 5  # every fault-bearing scenario fired

    # each scripted scenario lands on its intended disposition
    assert all(o.matched_expectation for o in outcomes), [
        (o.scenario, o.disposition) for o in outcomes if not o.matched_expectation
    ]


def test_every_disposition_is_a_known_bucket(seeded_db, tmp_path):
    _, outcomes, _ = build_report(trace_dir=tmp_path)
    allowed = {"recovered", "clarified", "failed_gracefully", "crashed", "hung"}
    assert {o.disposition for o in outcomes} <= allowed


def test_render_report_is_a_table_with_one_row_per_scenario(seeded_db, tmp_path):
    metrics, outcomes, report = build_report(trace_dir=tmp_path)
    text = render_report(metrics, outcomes)
    assert "# Failure recovery" in text
    assert "| Scenario | Injected fault |" in text
    assert f"Recovery rate (recovered or clarified): **{metrics.recovery_rate:.0%}**" in text
    body_rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "---" not in ln]
    assert len(body_rows) == 1 + len(outcomes)  # header + one per scenario


def test_compute_metrics_on_a_hand_built_list():
    from backend.agent.recovery import Outcome

    outs = [
        Outcome("a", "f", "recovered", "", 2, 1, 1, 0.0, True),
        Outcome("b", "f", "clarified", "", 0, 0, 0, 0.0, True),
        Outcome("c", "f", "failed_gracefully", "", 2, 0, 2, 0.0, True),
    ]
    m = compute_metrics(outs)
    assert m.tool_calls == 4 and m.tool_calls_ok == 1
    assert m.tool_call_success_rate == 0.25
    assert m.recovered == 1 and m.clarified == 1 and m.failed_gracefully == 1
    # b has 0 faults and no "cues" fault text -> not counted as disrupted
    assert m.recovery_rate == 0.5  # (recovered a + clarified none-of-disrupted) / 2 disrupted
    assert m.graceful_handling_rate == 1.0
