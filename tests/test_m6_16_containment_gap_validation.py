from __future__ import annotations

from evaluation.m6_16_containment_gap_validation import build_validation


def test_m6_16_replays_all_fifteen_survivors_on_real_compiler_path() -> None:
    result = build_validation()
    assert result.survivor_count == 15
    assert result.cluster_counts == {
        "contradictory_cancellation": 6,
        "unsupported_refund_reason": 9,
    }
    assert result.pre_fix_executable_survivors == 15
    assert result.post_fix_guard_interventions == 15
    assert result.post_fix_executable_survivors == 0
    assert result.post_fix_executions == 0


def test_m6_16_positive_controls_pass() -> None:
    result = build_validation()
    assert result.positive_control_count == 4
    assert result.positive_control_pass_count == 4


def test_m6_16_is_offline_only() -> None:
    result = build_validation()
    assert result.model_calls_performed == 0
    assert result.d2c_reruns_performed == 0
    assert result.status == "COMPLETE"
