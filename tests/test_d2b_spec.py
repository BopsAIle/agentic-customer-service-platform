from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.d2b_spec import (
    D2A_DECISION_REVISION,
    D2bExperimentSpec,
    D2bReviewApproval,
    assert_execution_approved,
    canonical_d2b_spec,
)


def test_d2b_machine_spec_matches_typed_canonical_spec() -> None:
    tracked = D2bExperimentSpec.model_validate_json(
        Path("evaluation/decisions/d2b_experiment_spec_v1.json").read_text(encoding="utf-8")
    )
    assert tracked == canonical_d2b_spec()
    assert tracked.status == "PREPARED_NOT_APPROVED"
    assert tracked.d2a_decision_revision == D2A_DECISION_REVISION


def test_d2b_uses_only_d2a_eligible_luna_and_fixed_84_attempt_strategy() -> None:
    spec = canonical_d2b_spec()
    assert [candidate.model for candidate in spec.eligible_candidates] == ["gpt-5.6-luna"]
    assert spec.dataset_strategy["case_count"] == 28
    assert spec.dataset_strategy["runs_per_case"] == 3
    assert spec.dataset_strategy["measured_attempts_per_model"] == 84
    assert spec.direct_tool_v1_comparison_arm is False
    assert spec.architecture_frozen is True
    assert spec.production_defaults_changed is False


def test_d2b_metrics_and_artifact_contract_are_complete() -> None:
    spec = canonical_d2b_spec()
    assert {metric.name for metric in spec.metrics} == {
        "routing_correctness",
        "semantic_target_correctness",
        "clarification_quality",
        "safety_violations",
        "hallucinated_identifiers",
        "compiler_correctness",
        "resolver_correctness",
        "consistency",
        "latency",
        "token_and_cost_accounting",
    }
    assert spec.artifact_requirements["atomic_publish_required"] is True
    assert spec.artifact_requirements["artifact_sha256_required"] is True
    assert spec.artifact_requirements["hash_recheck_after_validation"] is True


def test_d2b_execution_fails_closed_without_matching_review_approval() -> None:
    spec = canonical_d2b_spec()
    with pytest.raises(RuntimeError, match="D2B_REVIEW_APPROVAL_REQUIRED"):
        assert_execution_approved(spec, None)
    wrong = D2bReviewApproval(
        status="APPROVED",
        approval_gate_version="d2b_review_approval_gate_v1",
        spec_version="d2b_semantic_behavioral_matrix_v1",
        decision_record_id="model_compatibility_d2a_v1",
        approval_record_id="review-record",
    ).model_copy(update={"approval_gate_version": "wrong"})
    with pytest.raises(RuntimeError, match="D2B_REVIEW_APPROVAL_MISMATCH"):
        assert_execution_approved(spec, wrong)


def test_d2b_matching_review_approval_only_unlocks_preflight() -> None:
    spec = canonical_d2b_spec()
    approval = D2bReviewApproval(
        status="APPROVED",
        approval_gate_version="d2b_review_approval_gate_v1",
        spec_version="d2b_semantic_behavioral_matrix_v1",
        decision_record_id="model_compatibility_d2a_v1",
        approval_record_id="review-record",
    )
    assert_execution_approved(spec, approval)


def test_d2b_spec_has_no_execution_or_artifact_side_effects(tmp_path: Path) -> None:
    before = list(tmp_path.iterdir())
    payload = canonical_d2b_spec().model_dump(mode="json")
    after = list(tmp_path.iterdir())
    assert before == after == []
    serialized = json.dumps(payload)
    assert "OPENAI_API_KEY" not in serialized
    assert "Authorization" not in serialized
    source = Path("evaluation/d2b_spec.py").read_text(encoding="utf-8")
    assert "OpenAICompatibleProvider" not in source
    assert ".decide(" not in source
    assert "artifacts/live-eval" in serialized
