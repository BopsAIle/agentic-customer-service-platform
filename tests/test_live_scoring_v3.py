from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.live_scoring import LiveAttempt
from evaluation.live_scoring_v3 import (
    CASE_SET_SHA256,
    CASE_SET_VERSION,
    PAIR_MANIFEST,
    PROMPT_HASH,
    _no_tool,
    _routing_correct,
    exact_decision_signature,
    failure_labels,
    rescore_attempts,
    rescore_file,
    semantic_outcome_signature,
    validate_pair_manifest,
)


def attempt(
    *,
    expected_tools: list[str],
    actual_tool: str | None,
    expect_clarification: bool = False,
    clarification_correct: bool | None = None,
    actual_intent: str = "order_cancel",
    arguments: dict[str, object] | None = None,
    case_id: str = "test-case",
    run_number: int = 1,
) -> LiveAttempt:
    return LiveAttempt(
        case_id=case_id,
        language="en",
        category="cancellation",
        run_number=run_number,
        schema_valid=True,
        actual_intent=actual_intent,
        expected_intents=[actual_intent],
        actual_tool=actual_tool,
        expected_tools=expected_tools,
        argument_structural_valid=True if actual_tool else None,
        argument_semantic_correct=True if actual_tool else None,
        clarification_correct=clarification_correct if expect_clarification else None,
        actual_arguments=arguments or {},
        latency_ms=1.0,
    )


def test_action_tool_routing_accepts_only_expected_tool() -> None:
    correct = attempt(expected_tools=["cancel_order"], actual_tool="cancel_order")
    wrong = attempt(expected_tools=["cancel_order"], actual_tool="get_order")
    abstained = attempt(expected_tools=["cancel_order"], actual_tool=None)

    assert _routing_correct(correct)
    assert not _routing_correct(wrong)
    assert not _routing_correct(abstained)


def test_no_tool_abstention_is_separate_from_clarification() -> None:
    abstained = attempt(
        expected_tools=[],
        actual_tool=None,
        expect_clarification=True,
        clarification_correct=False,
    )
    wrong = attempt(expected_tools=[], actual_tool="cancel_order")

    assert _no_tool(abstained)
    assert _routing_correct(abstained)
    assert failure_labels(abstained) == ["clarification_miss"]
    assert not _routing_correct(wrong)
    assert "missed_abstention" in failure_labels(wrong)


def test_multiple_acceptable_tools_are_any_match() -> None:
    item = attempt(
        expected_tools=["get_order", "get_customer_orders"], actual_tool="get_customer_orders"
    )
    assert _routing_correct(item)


def test_provider_and_schema_failures_are_not_inferred_as_abstention() -> None:
    item = attempt(expected_tools=[], actual_tool=None)
    item.provider_failure = True
    item.schema_valid = False
    item.structured_output_failure = True
    item.failure_category = "llm_unavailable"

    assert not item.schema_valid  # v3 excludes it from the routing denominator
    assert failure_labels(item) == ["provider_failure"]


def test_provider_failure_is_excluded_from_routing_denominator() -> None:
    source = Path("artifacts/live-eval/qwen2_5_7b_instruct_20260812T213229Z.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["attempts"][0].update(
        {
            "schema_valid": False,
            "provider_failure": True,
            "actual_intent": None,
            "actual_tool": None,
            "actual_arguments": {},
            "failure_category": "llm_unavailable",
        }
    )
    report = rescore_attempts(
        [LiveAttempt.model_validate(item) for item in raw["attempts"]],
        metadata=raw["metadata"],
    )

    provider = report.attempt_level["provider_success"]
    overall = report.attempt_level["metrics"]["overall_routing"]
    assert provider.numerator == 83
    assert provider.denominator == 84
    assert overall.denominator == 83


def test_consistency_ignores_reason_and_key_order_but_preserves_target() -> None:
    first = attempt(
        expected_tools=["cancel_order"],
        actual_tool="cancel_order",
        arguments={"order_id": 3, "customer_id": 1},
        case_id="same",
        run_number=1,
    )
    second = first.model_copy(
        update={"actual_arguments": {"customer_id": 1, "order_id": 3}, "run_number": 2}
    )
    third = first.model_copy(
        update={"actual_arguments": {"customer_id": 1, "order_id": 4}, "run_number": 3}
    )

    assert exact_decision_signature(first) == exact_decision_signature(second)
    assert semantic_outcome_signature(first) == semantic_outcome_signature(second)
    assert semantic_outcome_signature(first) != semantic_outcome_signature(third)


def test_pair_manifest_is_complete_and_validated() -> None:
    validate_pair_manifest()
    assert len(PAIR_MANIFEST) == 14


def test_pair_manifest_rejects_duplicate_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = list(PAIR_MANIFEST)
    duplicate[1] = ("duplicate", duplicate[0][1], duplicate[1][2])
    monkeypatch.setattr("evaluation.live_scoring_v3.PAIR_MANIFEST", tuple(duplicate))

    with pytest.raises(ValueError, match="duplicates"):
        validate_pair_manifest()


def test_rescore_is_offline_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path("artifacts/live-eval/qwen2_5_7b_instruct_20260812T213229Z.json")
    frozen = tmp_path / source.name
    frozen.write_bytes(source.read_bytes())
    before = frozen.read_bytes()
    provider_called = False

    def fail_provider(*args: object, **kwargs: object) -> None:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("rescore must not call a provider")

    monkeypatch.setattr("app.agent.llm.provider.ChatOpenAI", fail_provider)
    output = tmp_path / "rescored.json"
    report = rescore_file(frozen, output)

    assert frozen.read_bytes() == before
    assert output.exists()
    assert report.metadata["source_artifact_sha256"]
    assert report.metadata["rescored_with"] == "live_scoring_v3"
    assert report.metadata["model_outputs_changed"] is False
    assert report.metadata["case_set_changed"] is False
    assert report.metadata["prompt_changed"] is False
    assert provider_called is False


def test_rescore_v3_has_explicit_legacy_metric() -> None:
    source = Path("artifacts/live-eval/qwen2_5_7b_instruct_20260812T213229Z.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    metadata = raw["metadata"]
    report = rescore_attempts(
        [LiveAttempt.model_validate(item) for item in raw["attempts"]],
        metadata=metadata,
    )
    assert "tool_selection_accuracy" not in report.attempt_level
    assert report.attempt_level["legacy_tool_selection"]["deprecated"] is True
    assert report.metadata["case_set_version"] == CASE_SET_VERSION
    assert report.metadata["case_set_sha256"] == CASE_SET_SHA256
    assert report.metadata["prompt_hash"] == PROMPT_HASH


def test_consistency_reports_eligible_and_ineligible_cases() -> None:
    source = Path("artifacts/live-eval/qwen2_5_7b_instruct_20260812T213229Z.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    attempts = [LiveAttempt.model_validate(item) for item in raw["attempts"]]
    case_attempts = [item for item in attempts if item.case_id == "en-order-latest"]
    case_attempts[-1].schema_valid = False
    report = rescore_attempts(
        attempts,
        metadata={
            "case_set_version": CASE_SET_VERSION,
            "case_set_sha256": CASE_SET_SHA256,
            "prompt_hash": PROMPT_HASH,
            "runs_per_case": 3,
        },
    )
    consistency = report.consistency
    assert consistency["unique_case_count"] == 28
    assert consistency["consistency_eligible_cases"] == 27
    assert consistency["consistency_ineligible_cases"] == 1
    assert consistency["exact_decision_consistent_cases"]["eligible"] == 27
    assert consistency["semantic_outcome_consistent_cases"]["eligible"] == 27
