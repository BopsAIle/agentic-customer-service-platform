from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus, DecisionCompiler
from app.agent.schemas import AgentRequestType, Intent, SemanticDecision, SemanticTarget
from app.core.context import ExecutionContext
from app.tools.refunds import RequestRefundInput
from evaluation.architecture_ab import ArchitectureOutcome
from evaluation.architecture_ab_d1b_rescore import (
    REFUND_REASON_CASE_ID,
    SOURCE_HASHES,
    _rescore_attempts,
    dataset_diff,
    execution_path_correct,
    rescore,
)
from evaluation.fixtures import evaluation_session
from evaluation.live_cases import (
    LIVE_CASE_SET_V1_2_VERSION,
    live_cases_v1_1,
    live_cases_v1_2,
)
from evaluation.live_scoring import case_set_metadata
from evaluation.live_scoring_v3 import PAIR_MANIFEST


def _outcome(
    case_id: str,
    contract: str,
    *,
    run_index: int = 1,
    tool: str | None = None,
    target: dict[str, Any] | None = None,
    arguments: dict[str, object] | None = None,
    compile_status: str | None = None,
) -> ArchitectureOutcome:
    case = next(case for case in live_cases_v1_2() if case.id == case_id)
    clarification = tool is None
    return ArchitectureOutcome(
        case_id=case_id,
        language=case.language,
        category=case.category,
        run_index=run_index,
        contract_version=contract,
        expected_tools=list(case.expected_tools),
        provider_success=True,
        schema_valid=True,
        model_intent=(case.expected_intents[0].value if case.expected_intents else None),
        model_target=target,
        model_clarification=clarification,
        model_clarification_correct=True,
        compile_status=compile_status or ("direct_action" if tool else "direct_no_action"),
        actual_tool=tool,
        actual_arguments=arguments or {},
        provider_latency_ms=1.0,
        end_to_end_latency_ms=1.0,
        intent_correct=True if case.expected_intents else None,
        target_entity_correct=True if target else None,
        effective_clarification_correct=True,
        routing_correct=True,
        routing_success_over_total=True,
        pre_policy_unsafe_action=False,
        model_unsafe_proposal=False if contract == "direct_tool_v1" else None,
        compiler_unsafe_action=False if contract == "semantic_decision_v3" else None,
        hallucinated_identifier=False,
        compiler_mapping_correct=True if contract == "semantic_decision_v3" else None,
        argument_structural_correct=True if contract == "direct_tool_v1" else None,
        argument_semantic_correct=True if contract == "direct_tool_v1" else None,
        semantic_reference_correctness=True if target else None,
        exact_signature=f"{case_id}:{run_index}:{contract}:{tool}",
        normalized_semantic_signature=f"{case_id}:{run_index}:{contract}:{tool}",
    )


def test_live_eval_v1_2_changes_only_refund_reason_oracle() -> None:
    changes = dataset_diff()
    assert set(changes) == {REFUND_REASON_CASE_ID}
    assert set(changes[REFUND_REASON_CASE_ID]) == {
        "expected_tools",
        "argument_rules",
        "expect_clarification",
    }
    old = {case.id: case for case in live_cases_v1_1()}
    new = {case.id: case for case in live_cases_v1_2()}
    assert len(new) == 28
    assert sum(case.language == "en" for case in new.values()) == 14
    assert sum(case.language == "tr" for case in new.values()) == 14
    assert all(old[case_id].input == new[case_id].input for case_id in old)
    paired_ids = {case_id for _, en_id, tr_id in PAIR_MANIFEST for case_id in (en_id, tr_id)}
    assert paired_ids == set(old) == set(new)
    historical_metadata = case_set_metadata(list(old.values()), version="live_eval_v1_1")
    assert historical_metadata["sha256"] == (
        "ad00fd8120e8c5187f667ee95ae7c93c387ed371f168af9d2cd76bb34631bd08"
    )
    metadata = case_set_metadata(list(new.values()), version=LIVE_CASE_SET_V1_2_VERSION)
    assert metadata["sha256"] == (
        "d8a10741dbb90e8a4de3b09098de36c4969c0b72944d253e37c9580279064eb5"
    )


def test_latest_order_execution_equivalence_is_architecture_neutral() -> None:
    case = next(case for case in live_cases_v1_2() if case.id == "en-order-latest")
    direct = _outcome("en-order-latest", "direct_tool_v1", tool="get_customer_orders")
    semantic = _outcome(
        "en-order-latest",
        "semantic_decision_v3",
        tool="get_order",
        target={"type": "latest_order"},
        arguments={"order_id": 3},
        compile_status=CompileStatus.COMPILED_ACTION.value,
    )
    wrong_order = semantic.model_copy(update={"actual_arguments": {"order_id": 2}})
    wrong_reference = semantic.model_copy(
        update={"model_target": {"type": "explicit_order", "order_id": 3}}
    )
    unrelated = direct.model_copy(update={"actual_tool": "get_customer"})
    assert execution_path_correct(case, direct, expected_latest_order_id=3)
    assert execution_path_correct(case, semantic, expected_latest_order_id=3)
    assert not execution_path_correct(case, wrong_order, expected_latest_order_id=3)
    assert not execution_path_correct(case, wrong_reference, expected_latest_order_id=3)
    assert not execution_path_correct(case, unrelated, expected_latest_order_id=3)


def test_resolver_is_not_penalized_for_post_resolution_compiler_clarification() -> None:
    source = _outcome(
        REFUND_REASON_CASE_ID,
        "semantic_decision_v3",
        target={"type": "explicit_order", "order_id": 6},
        compile_status=CompileStatus.CLARIFICATION_REQUIRED.value,
    )
    source.business_resolution_correct = False
    source.business_resolution_correct_given_correct_reference = False
    corrected, _ = _rescore_attempts(
        [source],
        {case.id: case for case in live_cases_v1_2()},
        {},
    )
    assert corrected[0].business_resolution_correct is True
    assert corrected[0].business_resolution_correct_given_correct_reference is True
    assert corrected[0].compile_status == CompileStatus.CLARIFICATION_REQUIRED.value


def test_refund_reason_is_required_and_missing_reason_clarifies() -> None:
    with pytest.raises(ValidationError):
        RequestRefundInput.model_validate({"customer_id": 3, "order_id": 6})
    with evaluation_session() as session:
        result = DecisionCompiler(BusinessTargetResolver(session)).compile(
            SemanticDecision(
                intent=Intent.REFUND_REQUEST,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=6),
            ),
            ExecutionContext.model_validate(
                {
                    "request_id": "offline-refund-audit",
                    "conversation_id": "offline-refund-audit",
                    "principal": {
                        "actor_id": "offline-auditor",
                        "actor_type": "support_operator",
                        "roles": ["support_operator"],
                    },
                    "effective_customer_id": 3,
                }
            ),
        )
    assert result.status is CompileStatus.CLARIFICATION_REQUIRED
    assert result.selected_tool is None
    assert result.reason == "A refund reason is required."


def test_refund_with_explicit_reason_can_compile_to_action() -> None:
    with evaluation_session() as session:
        result = DecisionCompiler(BusinessTargetResolver(session)).compile(
            SemanticDecision(
                intent=Intent.REFUND_REQUEST,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=6),
                reason="Package arrived damaged.",
            ),
            ExecutionContext.model_validate(
                {
                    "request_id": "offline-refund-with-reason",
                    "conversation_id": "offline-refund-with-reason",
                    "principal": {
                        "actor_id": "offline-auditor",
                        "actor_type": "support_operator",
                        "roles": ["support_operator"],
                    },
                    "effective_customer_id": 3,
                }
            ),
        )
    assert result.status is CompileStatus.COMPILED_ACTION
    assert result.selected_tool == "request_refund"
    assert result.tool_arguments == {
        "customer_id": 3,
        "order_id": 6,
        "reason": "Package arrived damaged.",
    }


def test_refund_oracle_distinguishes_missing_reason_from_omitted_extraction() -> None:
    cases = {case.id: case for case in live_cases_v1_2()}
    missing_user_reason = _outcome(
        REFUND_REASON_CASE_ID,
        "semantic_decision_v3",
        target={"type": "explicit_order", "order_id": 6},
        compile_status=CompileStatus.CLARIFICATION_REQUIRED.value,
    )
    supplied_but_omitted = _outcome(
        "en-refund-delivered",
        "semantic_decision_v3",
        target={"type": "explicit_order", "order_id": 1},
        compile_status=CompileStatus.CLARIFICATION_REQUIRED.value,
    )
    corrected, _ = _rescore_attempts([missing_user_reason, supplied_but_omitted], cases, {})
    assert corrected[0].routing_correct is True
    assert corrected[0].effective_clarification_correct is True
    assert corrected[1].routing_correct is False
    assert corrected[1].effective_clarification_correct is False


def test_offline_rescore_is_reproducible_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = live_cases_v1_2()
    direct: list[ArchitectureOutcome] = []
    semantic: list[ArchitectureOutcome] = []
    for case in cases:
        for run_index in range(1, 4):
            tool = case.expected_tools[0] if case.expected_tools else None
            direct.append(_outcome(case.id, "direct_tool_v1", run_index=run_index, tool=tool))
            semantic.append(
                _outcome(
                    case.id,
                    "semantic_decision_v3",
                    run_index=run_index,
                    tool=tool,
                    compile_status=(
                        CompileStatus.COMPILED_ACTION.value
                        if tool
                        else CompileStatus.CLARIFICATION_REQUIRED.value
                    ),
                )
            )
    direct_source = SimpleNamespace(attempts=direct, layer_b={})
    semantic_source = SimpleNamespace(attempts=semantic, layer_b={})
    monkeypatch.setattr(
        "evaluation.architecture_ab_d1b_rescore._load_sources",
        lambda _: (direct_source, semantic_source),
    )
    monkeypatch.setattr(
        "evaluation.architecture_ab_d1b_rescore._source_hashes", lambda _: SOURCE_HASHES
    )
    first = rescore(Path("unused"))
    second = rescore(Path("unused"))
    assert first == second
    assert first[0]["provenance"]["model_calls_performed"] == 0
    assert first[1]["status"] == "COMPLETE"
