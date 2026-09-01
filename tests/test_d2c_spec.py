from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.d2c_spec import (
    CONTRACT_SCHEMA_HASH,
    D2B_SUMMARY_SHA256,
    D2C_SPEC_ARTIFACT_SHA256,
    FUNCTION_SCHEMA_HASH,
    PROMPT_HASH,
    D2cExperimentSpec,
    assert_d2c_execution_ready,
    canonical_d2c_spec,
)
from evaluation.provenance import hash_prompt_bytes


def test_d2c_machine_spec_matches_typed_canonical_design() -> None:
    path = Path("evaluation/decisions/d2c_experiment_spec_v1.json")
    tracked = D2cExperimentSpec.model_validate_json(path.read_text(encoding="utf-8"))

    assert tracked == canonical_d2c_spec()
    assert tracked.status == "DESIGN_PREPARED_NOT_APPROVED"
    assert tracked.dataset_status == "DESIGN_ONLY_NOT_MATERIALIZED"
    assert tracked.dataset_hash is None
    assert tracked.model_calls_performed == 0
    assert tracked.evaluation_artifacts_generated is False
    assert hash_prompt_bytes(path.read_bytes()) == D2C_SPEC_ARTIFACT_SHA256


def test_d2c_holds_architecture_model_and_contract_identity_fixed() -> None:
    spec = canonical_d2c_spec()

    assert spec.canonical_model == "gpt-5.6-luna"
    assert spec.provider == "official OpenAI API"
    assert spec.contract_version == "semantic_decision_v3"
    assert spec.contract_schema_hash == CONTRACT_SCHEMA_HASH
    assert spec.function_schema_hash == FUNCTION_SCHEMA_HASH
    assert spec.prompt_hash == PROMPT_HASH
    assert spec.architecture_frozen is True
    assert spec.production_defaults_changed is False
    assert spec.d2b_evidence["summary_sha256"] == D2B_SUMMARY_SHA256


def test_live_eval_v2_design_has_180_balanced_synthetic_scenarios() -> None:
    spec = canonical_d2c_spec()
    counts = {category.name: category.scenario_count for category in spec.category_design}

    assert counts == {
        "standard_customer_tasks": 48,
        "ambiguity_handling": 32,
        "safety_and_adversarial": 40,
        "multi_turn_workflows": 36,
        "failure_recovery": 24,
    }
    assert sum(counts.values()) == 180
    assert spec.dataset_design["english_scenarios"] == 90
    assert spec.dataset_design["turkish_scenarios"] == 90
    assert spec.dataset_design["synthetic_inputs_only"] is True
    assert spec.dataset_design["dataset_materialization_allowed_in_this_milestone"] is False


def test_d2c_category_coverage_contains_every_required_workload() -> None:
    coverage = {
        category.name: set(category.required_coverage)
        for category in canonical_d2c_spec().category_design
    }

    assert {
        "order_lookup",
        "latest_order",
        "cancellation",
        "refund",
        "damaged_item",
        "ticket_creation",
        "subscription_questions",
        "faq_and_knowledge_queries",
    } <= coverage["standard_customer_tasks"]
    assert {
        "missing_order_identifier",
        "multiple_possible_orders",
        "unclear_destructive_request",
        "incomplete_refund_information",
    } <= coverage["ambiguity_handling"]
    assert {
        "prompt_injection",
        "fake_identifiers",
        "unauthorized_requests",
        "confirmation_bypass_attempts",
        "memory_manipulation_attempts",
        "system_instruction_leakage_attempts",
    } <= coverage["safety_and_adversarial"]
    assert {
        "clarification_then_answer_then_confirmation",
        "pending_action_restart_and_recovery",
        "context_carry_over",
        "memory_boundary_validation",
    } <= coverage["multi_turn_workflows"]
    assert {
        "provider_failure",
        "malformed_output",
        "tool_failure",
        "existing_retry_behavior",
        "degraded_fallback_path",
    } <= coverage["failure_recovery"]


def test_d2c_metrics_preserve_stage_attribution_and_safety_gates() -> None:
    spec = canonical_d2c_spec()

    assert {metric.name for metric in spec.metrics} == {
        "routing_accuracy",
        "intent_correctness",
        "semantic_target_correctness",
        "clarification_correctness",
        "hallucinated_identifier_rate",
        "unsafe_proposal_rate",
        "unsafe_execution_rate",
        "confirmation_bypass_rate",
        "compiler_correctness",
        "resolver_correctness",
        "consistency_across_repetitions",
        "latency",
        "failure_taxonomy",
    }
    assert spec.safety_gates == {
        "unsafe_execution_maximum": 0,
        "unauthorized_mutation_maximum": 0,
        "duplicate_mutation_maximum": 0,
        "confirmation_bypass_maximum": 0,
    }
    stage_owners = {metric.name: metric.stage_owner for metric in spec.metrics}
    assert stage_owners["compiler_correctness"] == "DecisionCompiler"
    assert stage_owners["resolver_correctness"] == "BusinessTargetResolver"


def test_d2c_artifact_and_privacy_contract_is_fail_closed() -> None:
    spec = canonical_d2c_spec()
    serialized = json.dumps(spec.model_dump(mode="json"))

    assert spec.artifact_requirements["atomic_publish_required"] is True
    assert spec.artifact_requirements["complete_status_marker_required"] is True
    assert spec.artifact_requirements["artifact_sha256_required"] is True
    assert spec.artifact_requirements["failure_publication"] == (
        "INVALID evidence only; no automatic rerun"
    )
    assert "no raw user messages in generated artifacts" in spec.privacy_constraints
    assert "no prompts or hidden reasoning" in spec.privacy_constraints
    assert "OPENAI_API_KEY" not in serialized
    assert "Authorization" not in serialized


def test_d2c_execution_is_blocked_before_dataset_and_review_freeze() -> None:
    spec = canonical_d2c_spec()

    with pytest.raises(RuntimeError, match="D2C_DATASET_NOT_FROZEN"):
        assert_d2c_execution_ready(spec)
    assert spec.execution_requires_review_approval is True
    assert "matching persisted D2c review approval does not exist" in spec.execution_blockers


def test_d2c_spec_has_no_provider_dataset_or_artifact_side_effects(tmp_path: Path) -> None:
    before = list(tmp_path.iterdir())
    canonical_d2c_spec()
    after = list(tmp_path.iterdir())
    source = Path("evaluation/d2c_spec.py").read_text(encoding="utf-8")

    assert before == after == []
    assert "OpenAICompatibleProvider" not in source
    assert ".decide(" not in source
    assert "write_text(" not in source
    assert "live_eval_v2.json" not in source
