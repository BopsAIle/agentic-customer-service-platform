from __future__ import annotations

from app.agent.decision_compiler import BusinessTargetResolver, DecisionCompiler
from app.agent.schemas import (
    AgentRequestType,
    Intent,
    SemanticDecision,
    SemanticTarget,
    StructuredDecision,
)
from evaluation.architecture_ab import (
    ArchitectureOutcome,
    ArmArtifact,
    _direct_outcome,
    _paired_first_order,
    _semantic_outcome,
    compare_artifacts,
)
from evaluation.architecture_ab_audit import _identifier_audit, _unsafe_reasons
from evaluation.fixtures import evaluation_session
from evaluation.live_cases import live_cases
from evaluation.live_scoring_v3 import PAIR_MANIFEST


def _direct(case_id: str, *, tool: str | None, intent: Intent) -> ArchitectureOutcome:
    case = next(case for case in live_cases() if case.id == case_id)
    decision = StructuredDecision(
        intent=intent,
        request_type=AgentRequestType.WRITE_ACTION,
        tool_name=tool,
        arguments={"customer_id": case.customer_id, "order_id": 3} if tool else {},
    )
    return _direct_outcome(
        case,
        1,
        decision,
        True,
        1.0,
        1.0,
        execution_order="direct_tool_v1",
    )


def test_direct_correct_wrong_and_abstention_are_distinct() -> None:
    correct = _direct("en-cancel-valid", tool="cancel_order", intent=Intent.ORDER_CANCEL)
    wrong = _direct("en-cancel-valid", tool="get_order", intent=Intent.ORDER_LOOKUP)
    abstention = _direct("en-cancel-valid", tool=None, intent=Intent.UNKNOWN)
    assert correct.routing_correct is True
    assert wrong.routing_correct is False
    assert abstention.routing_correct is False


def test_direct_correct_no_tool_abstention() -> None:
    outcome = _direct("en-clarify-order", tool=None, intent=Intent.UNKNOWN)
    assert outcome.routing_correct is True
    assert outcome.effective_clarification_correct is True


def test_semantic_correct_intent_compiles_to_canonical_action() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-valid")
    with evaluation_session() as session:
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        outcome = _semantic_outcome(
            case,
            1,
            SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=3),
            ),
            True,
            1.0,
            1.1,
            0.1,
            None,
            execution_order="semantic_decision_v2",
            compiler=compiler,
        )
    assert outcome.actual_tool == "cancel_order"
    assert outcome.expected_tools == ["cancel_order"]
    assert outcome.routing_correct is True
    assert outcome.compiler_correct_given_correct_semantics is True
    assert outcome.compile_status == "compiled_action"


def test_semantic_wrong_intent_is_not_a_compiler_failure() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-valid")
    with evaluation_session() as session:
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        outcome = _semantic_outcome(
            case,
            1,
            SemanticDecision(
                intent=Intent.ORDER_LOOKUP, target=SemanticTarget(type="explicit_order", order_id=3)
            ),
            True,
            1.0,
            1.1,
            0.1,
            None,
            execution_order="semantic_decision_v2",
            compiler=compiler,
        )
    assert outcome.intent_correct is False
    assert outcome.routing_correct is False
    assert "semantic_intent_failure" in outcome.failure_labels


def test_semantic_missing_target_intervention_is_safe() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-no-id")
    with evaluation_session() as session:
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        outcome = _semantic_outcome(
            case,
            1,
            SemanticDecision(intent=Intent.ORDER_CANCEL, clarification_required=False),
            True,
            1.0,
            1.1,
            0.1,
            None,
            execution_order="semantic_decision_v2",
            compiler=compiler,
        )
    assert outcome.compile_status == "clarification_required"
    assert outcome.routing_correct is True
    assert outcome.compiler_clarification_intervention is True
    assert outcome.pre_policy_unsafe_action is False


def test_forensic_audit_rejects_hyphenated_fake_token_as_id_grounding() -> None:
    case = next(case for case in live_cases() if case.id == "tr-fake-id")
    outcome = ArchitectureOutcome(
        case_id=case.id,
        language=case.language,
        category=case.category,
        run_index=1,
        contract_version="semantic_decision_v2",
        provider_success=True,
        schema_valid=True,
        model_target={"type": "explicit_order", "order_id": 999},
        actual_tool="cancel_order",
        actual_arguments={"order_id": 999},
        compile_status="compiled_action",
        pre_policy_unsafe_action=False,
        hallucinated_identifier=True,
        provider_latency_ms=1.0,
        end_to_end_latency_ms=1.0,
    )
    audit = _identifier_audit(outcome, case)
    assert audit["user_input_order_id_evidence"] == []
    assert audit["grounding_classification"] == "MODEL_GENERATED_UNGROUNDED_ID"


def test_forensic_audit_separates_symbolic_wrong_reference_from_id_hallucination() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-no-id")
    outcome = ArchitectureOutcome(
        case_id=case.id,
        language=case.language,
        category=case.category,
        run_index=1,
        contract_version="semantic_decision_v2",
        provider_success=True,
        schema_valid=True,
        model_target={"type": "latest_order"},
        actual_tool="cancel_order",
        actual_arguments={"order_id": 3},
        compile_status="compiled_action",
        pre_policy_unsafe_action=True,
        provider_latency_ms=1.0,
        end_to_end_latency_ms=1.0,
    )
    assert _unsafe_reasons(outcome, case) == [
        "MISSING_REQUIRED_TARGET",
        "WRONG_TARGET_REFERENCE",
    ]


def test_business_resolution_metric_excludes_upstream_wrong_reference() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-no-id")
    with evaluation_session() as session:
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        outcome = _semantic_outcome(
            case,
            1,
            SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="latest_order"),
            ),
            True,
            1.0,
            1.1,
            0.1,
            None,
            execution_order="semantic_decision_v2",
            compiler=compiler,
        )
    assert outcome.semantic_reference_correctness is False
    assert outcome.business_resolution_correct is None
    assert outcome.business_resolution_correct_given_correct_reference is None


def test_provider_failure_is_visible_and_excluded_from_conditional_routing() -> None:
    case = next(case for case in live_cases() if case.id == "en-cancel-valid")
    outcome = _direct_outcome(
        case,
        1,
        None,
        False,
        30000.0,
        30000.0,
        timeout=True,
        error_type="TimeoutException",
        execution_order="direct_tool_v1",
    )
    assert outcome.provider_success is False
    assert outcome.schema_valid is False
    assert outcome.routing_correct is None
    assert outcome.routing_success_over_total is False


def _synthetic_arms() -> tuple[ArmArtifact, ArmArtifact]:
    cases = live_cases()
    direct: list[ArchitectureOutcome] = []
    semantic: list[ArchitectureOutcome] = []
    with evaluation_session() as session:
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        for case in cases:
            for run_index in range(1, 4):
                if case.expected_tools:
                    tool = case.expected_tools[0]
                    intent = case.expected_intents[0]
                    arguments = dict(case.expected_arguments)
                    if tool == "create_support_ticket":
                        arguments.update({"category": "delivery", "description": "package damaged"})
                    if tool == "request_refund":
                        arguments["reason"] = "damaged"
                    if tool == "escalate_to_human":
                        arguments.update(
                            {"priority": "urgent", "reason": "urgent", "summary": "help"}
                        )
                    direct_decision = StructuredDecision(
                        intent=intent,
                        request_type=AgentRequestType.WRITE_ACTION,
                        tool_name=tool,
                        arguments=arguments,
                    )
                    direct.append(
                        _direct_outcome(
                            case,
                            run_index,
                            direct_decision,
                            True,
                            1.0,
                            1.0,
                            execution_order="direct_tool_v1",
                        )
                    )
                    target = None
                    if "order_id" in case.expected_arguments:
                        order_id = case.expected_arguments["order_id"]
                        assert isinstance(order_id, int)
                        target = SemanticTarget(type="explicit_order", order_id=order_id)
                    semantic_decision = SemanticDecision(
                        intent=intent,
                        request_type=AgentRequestType.WRITE_ACTION,
                        target=target,
                        category="delivery" if tool == "create_support_ticket" else None,
                        description="package damaged" if tool == "create_support_ticket" else None,
                        reason="damaged"
                        if tool == "request_refund"
                        else "urgent"
                        if tool == "escalate_to_human"
                        else "",
                        priority="urgent" if tool == "escalate_to_human" else None,
                        summary="help" if tool == "escalate_to_human" else None,
                    )
                else:
                    direct_decision = StructuredDecision(
                        intent=Intent.UNKNOWN,
                        request_type=AgentRequestType.UNCLEAR,
                        tool_name=None,
                        arguments={},
                    )
                    direct.append(
                        _direct_outcome(
                            case,
                            run_index,
                            direct_decision,
                            True,
                            1.0,
                            1.0,
                            execution_order="direct_tool_v1",
                        )
                    )
                    semantic_decision = SemanticDecision(
                        intent=Intent.UNKNOWN,
                        request_type=AgentRequestType.UNCLEAR,
                        clarification_required=case.expect_clarification,
                    )
                semantic.append(
                    _semantic_outcome(
                        case,
                        run_index,
                        semantic_decision,
                        True,
                        1.0,
                        1.1,
                        0.1,
                        None,
                        execution_order="semantic_decision_v2",
                        compiler=compiler,
                    )
                )
    experiment = {"experiment_id": "synthetic", "arm": "direct_tool_v1"}
    return (
        ArmArtifact(
            experiment=experiment,
            provenance={},
            attempts=direct,
            layer_b={"unsafe_execution_rate": 0.0, "confirmation_bypass_rate": 0.0},
        ),
        ArmArtifact(
            experiment=experiment,
            provenance={},
            attempts=semantic,
            layer_b={"unsafe_execution_rate": 0.0, "confirmation_bypass_rate": 0.0},
        ),
    )


def test_paired_comparison_and_offline_rescore_are_deterministic() -> None:
    direct, semantic = _synthetic_arms()
    first = compare_artifacts(direct, semantic)
    second = compare_artifacts(direct, semantic)
    assert len(direct.attempts) == len(semantic.attempts) == 84
    assert len(PAIR_MANIFEST) == 14
    assert first == second
    assert first["scoring_version"] == "architecture_ab_scoring_v1_1"
    assert first["classification"] in {"BETTER", "MIXED", "EQUIVALENT", "WORSE", "INVALID"}
    assert (
        first["arms"]["semantic_decision_v2"]["contract_specific"]["compiled_action_correctness"][
            "eligible"
        ]
        > 0
    )


def test_paired_schedule_is_stable_and_counterbalanced() -> None:
    assert _paired_first_order(0, 1) == "semantic_decision_v2"
    assert _paired_first_order(0, 2) == "direct_tool_v1"
    assert _paired_first_order(7, 1) == "direct_tool_v1"
    assert _paired_first_order(7, 2) == "semantic_decision_v2"


def test_semantic_compiler_mapping_failure_is_attributed_separately() -> None:
    outcome = ArchitectureOutcome(
        case_id="en-cancel-valid",
        language="en",
        category="cancellation",
        run_index=1,
        contract_version="semantic_decision_v2",
        expected_tools=["cancel_order"],
        provider_success=True,
        schema_valid=True,
        model_intent="order_cancel",
        model_clarification=False,
        model_clarification_correct=True,
        compile_status="compiled_action",
        actual_tool="get_order",
        intent_correct=True,
        target_entity_correct=True,
        effective_clarification_correct=True,
        routing_correct=False,
        model_semantics_correct=True,
        compiler_correct_given_correct_semantics=False,
        failure_labels=["compiler_mapping_failure"],
        provider_latency_ms=1.0,
        end_to_end_latency_ms=1.0,
    )
    assert "compiler_mapping_failure" in outcome.failure_labels
