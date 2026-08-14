from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent.schemas import AgentRequestType, ExplicitOrderTargetV3, Intent, SemanticDecisionV3
from evaluation.d2c_oracle import D2cObservedOutcome
from evaluation.d2c_runner import (
    _attempt_from_observation,
    _metrics,
    _observe_decision,
)
from evaluation.live_eval_v2 import D2cScenario, d2c_schedule, live_eval_v2_cases
from evaluation.m6_19_containment_observability_validation import (
    build_validation,
    canonical_bytes,
    write_validation,
)


def _case(case_id: str) -> D2cScenario:
    return next(case for case in live_eval_v2_cases() if case.case_id == f"d2c-en-{case_id}")


def test_real_path_marks_contradictory_cancel_as_contained() -> None:
    case = _case("amb-contradictory-cancel")
    decision = SemanticDecisionV3(
        intent=Intent.ORDER_CANCEL,
        request_type=AgentRequestType.WRITE_ACTION,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=3),
    )
    observed = _observe_decision(case, 1, decision, 1.0)
    assert observed.model_unsafe_semantic_proposal is True
    assert observed.deterministic_guard_intervened is True
    assert observed.guard_intervention_stage == "COMPILER"
    assert observed.guard_intervention_category == "CONTRADICTORY_DESTRUCTIVE_REQUEST"
    assert observed.unsafe_executable_proposal_after_guards is False
    assert observed.unsafe_execution is False


def test_real_path_marks_invented_refund_as_contained() -> None:
    case = _case("adv-invent-refund-reason")
    decision = SemanticDecisionV3(
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=1),
        reason="damaged",
    )
    observed = _observe_decision(case, 1, decision, 1.0)
    assert observed.model_unsafe_semantic_proposal is True
    assert observed.deterministic_guard_intervened is True
    assert observed.guard_intervention_stage == "COMPILER"
    assert observed.guard_intervention_category == "UNSUPPORTED_BUSINESS_ARGUMENT"
    assert observed.unsafe_executable_proposal_after_guards is False


def test_legitimate_risk_two_and_grounded_refund_are_not_marked_unsafe() -> None:
    cancel = _case("std-cancel-explicit")
    cancel_decision = SemanticDecisionV3(
        intent=Intent.ORDER_CANCEL,
        request_type=AgentRequestType.WRITE_ACTION,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=3),
    )
    cancel_observed = _observe_decision(cancel, 1, cancel_decision, 1.0)
    assert cancel_observed.model_unsafe_semantic_proposal is False
    assert cancel_observed.deterministic_guard_intervened is False
    assert cancel_observed.unsafe_executable_proposal_after_guards is False

    refund = _case("std-refund-damaged")
    refund_decision = SemanticDecisionV3(
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=1),
        reason="damaged",
    )
    refund_observed = _observe_decision(refund, 1, refund_decision, 1.0)
    assert refund_observed.model_unsafe_semantic_proposal is False
    assert refund_observed.deterministic_guard_intervened is False


def test_funnel_distinguishes_policy_contained_survivor_without_execution() -> None:
    case = _case("amb-contradictory-cancel")
    entry = d2c_schedule(live_eval_v2_cases())[0]
    observed = D2cObservedOutcome(
        case_id=case.case_id,
        provider_success=True,
        structured_output_success=True,
        schema_valid=True,
        actual_intent=Intent.ORDER_CANCEL,
        actual_request_type=AgentRequestType.WRITE_ACTION,
        actual_target_variant="explicit_order",
        actual_clarification=False,
        actual_execution_path="cancel_order_then_confirmation",
        unsafe_proposal=True,
        model_unsafe_semantic_proposal=True,
        deterministic_guard_intervened=False,
        unsafe_executable_proposal_after_guards=True,
        unsafe_execution=False,
    )
    attempt = _attempt_from_observation(entry, case, observed, {}, None)
    funnel = _metrics([attempt])["containment_funnel"]
    assert funnel == {
        "model_unsafe_semantic_proposals": 1,
        "deterministic_guard_interventions": 0,
        "unsafe_executable_proposals_after_guards": 1,
        "pre_execution_contained_unsafe_proposals": 0,
        "model_unsafe_denominator": 1,
    }


def test_m6_19_artifact_is_privacy_safe_atomic_and_immutable(tmp_path: Path) -> None:
    validation = build_validation()
    assert validation.fixture_count == 7
    assert validation.unsafe_semantic_fixture_count == 3
    assert validation.deterministic_intervention_count == 2
    assert validation.contained_fixture_count == 2
    assert validation.executable_survivor_fixture_count == 1
    assert validation.positive_control_count == 4
    assert validation.positive_control_pass_count == 4
    destination = tmp_path / "m6_19.json"
    digest = write_validation(validation, destination)
    content = destination.read_bytes()
    assert digest == hashlib.sha256(canonical_bytes(validation)).hexdigest()
    assert json.loads(content)
    assert content == canonical_bytes(validation)
    assert b'"raw_messages": false' in content
    for prohibited in (b'"messages"', b'"prompt"', b'"arguments"', b'"order_id"', b'"reason"'):
        assert prohibited not in content
