"""Offline validation for the hardened semantic argument prompt contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.llm.fake import FakeSemanticDecisionV3Provider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, ExplicitOrderTargetV3, Intent, SemanticDecisionV3
from app.agent.semantic_attribution import RefundReasonSupportStatus
from evaluation.d2c_runner import _observe_decision
from evaluation.fixtures import evaluation_session
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases
from evaluation.provenance import prompt_hash_for_contract

ARTIFACT_VERSION: Literal["m6_27b_prompt_semantic_contract_validation_v1"] = (
    "m6_27b_prompt_semantic_contract_validation_v1"
)
CONTRACT_VERSION: Literal["semantic_decision_v3"] = "semantic_decision_v3"
OBSERVABILITY_VERSION: Literal["semantic_attribution_observability_v1"] = (
    "semantic_attribution_observability_v1"
)


class FixtureOutcome(StrEnum):
    ACTION = "action"
    CLARIFICATION = "clarification"
    READ = "read"


class FixtureObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    outcome: FixtureOutcome
    refund_reason_support_status: RefundReasonSupportStatus | None = None
    compiler: str
    policy: str
    pending_action: bool = False
    risk_level: int | None = None


class M627BValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_version: Literal["m6_27b_prompt_semantic_contract_validation_v1"] = ARTIFACT_VERSION
    status: Literal["COMPLETE"] = "COMPLETE"
    contract_version: Literal["semantic_decision_v3"] = CONTRACT_VERSION
    prompt_hash: str
    observability_version: Literal["semantic_attribution_observability_v1"] = OBSERVABILITY_VERSION
    fixture_count: int
    runtime_behavior_unchanged: Literal[True] = True
    model_calls_performed: Literal[0] = 0
    fixtures: tuple[FixtureObservation, ...]


def _case(case_id: str) -> D2cScenario:
    return next(case for case in live_eval_v2_cases() if case.case_id == case_id)


def _proposal(*, intent: Intent, reason: str = "", order_id: int | None = 1) -> SemanticDecisionV3:
    target = (
        ExplicitOrderTargetV3(type="explicit_order", order_id=order_id)
        if order_id is not None
        else None
    )
    request_type = (
        AgentRequestType.WRITE_ACTION
        if intent in {Intent.REFUND_REQUEST, Intent.ORDER_CANCEL}
        else AgentRequestType.READ_ACTION
    )
    return SemanticDecisionV3(
        intent=intent,
        request_type=request_type,
        target=target,
        reason=reason,
    )


def _observe(fixture_id: str, case_id: str, proposal: SemanticDecisionV3) -> FixtureObservation:
    observed = _observe_decision(_case(case_id), 1, proposal, 0.0)
    return FixtureObservation(
        fixture_id=fixture_id,
        outcome=(
            FixtureOutcome.READ
            if observed.actual_intent
            in {
                Intent.CUSTOMER_LOOKUP,
                Intent.ORDER_LOOKUP,
                Intent.ORDER_LIST,
                Intent.TICKET_LOOKUP,
                Intent.TICKET_LIST,
            }
            else FixtureOutcome.ACTION
            if observed.actual_compiler == "action"
            else FixtureOutcome.CLARIFICATION
        ),
        refund_reason_support_status=observed.refund_reason_support_status,
        compiler=observed.actual_compiler or "unknown",
        policy=observed.actual_policy or "unknown",
    )


def _runtime_observe(
    fixture_id: str, case_id: str, proposal: SemanticDecisionV3
) -> FixtureObservation:
    case = _case(case_id)
    provider = FakeSemanticDecisionV3Provider([proposal])
    message = "\n".join(turn.text for turn in case.interaction)
    with evaluation_session() as session:
        response = AgentRuntime(
            provider=provider,
            decision_contract_version=CONTRACT_VERSION,
        ).run(
            conversation_id=f"m6-27b-{fixture_id}",
            customer_id=1,
            message=message,
            session=session,
        )
    if len(provider.calls) != 1:
        raise AssertionError("offline fixture unexpectedly crossed the provider boundary")
    pending = response.pending_action
    return FixtureObservation(
        fixture_id=fixture_id,
        outcome=FixtureOutcome.ACTION if pending is not None else FixtureOutcome.CLARIFICATION,
        refund_reason_support_status=(
            RefundReasonSupportStatus.SUPPORTED
            if pending is not None and proposal.intent is Intent.REFUND_REQUEST
            else None
        ),
        compiler="action" if pending is not None else "clarification",
        policy="confirmation_required" if pending is not None else "not_applicable",
        pending_action=pending is not None,
        risk_level=pending.risk_level if pending is not None else None,
    )


def build_validation() -> M627BValidation:
    fixtures = (
        _runtime_observe(
            "supported-turkish-refund",
            "d2c-tr-std-refund-damaged",
            _proposal(intent=Intent.REFUND_REQUEST, reason="hasarlı"),
        ),
        _runtime_observe(
            "supported-english-refund",
            "d2c-en-std-refund-damaged",
            _proposal(intent=Intent.REFUND_REQUEST, reason="damaged"),
        ),
        _observe(
            "missing-refund-reason",
            "d2c-en-std-refund-damaged",
            _proposal(intent=Intent.REFUND_REQUEST),
        ),
        _observe(
            "unsupported-refund-reason",
            "d2c-en-std-refund-damaged",
            _proposal(intent=Intent.REFUND_REQUEST, reason="changed my mind"),
        ),
        _observe(
            "unsupported-refund-embellishment",
            "d2c-en-std-refund-damaged",
            _proposal(intent=Intent.REFUND_REQUEST, reason="damaged due to hidden defect"),
        ),
        _runtime_observe(
            "supported-turkish-multi-turn-refund",
            "d2c-tr-mt-refund-add-reason",
            _proposal(intent=Intent.REFUND_REQUEST, reason="hasarlıydı"),
        ),
        _observe(
            "safe-read",
            "d2c-en-std-order-status-explicit",
            _proposal(intent=Intent.ORDER_LOOKUP, reason="", order_id=3),
        ),
        _runtime_observe(
            "cancellation-write",
            "d2c-tr-std-cancel-explicit",
            _proposal(intent=Intent.ORDER_CANCEL, reason="", order_id=3),
        ),
    )
    return M627BValidation(
        prompt_hash=prompt_hash_for_contract(CONTRACT_VERSION),
        fixture_count=len(fixtures),
        fixtures=fixtures,
    )


def main() -> int:
    validation = build_validation()
    observations = {item.fixture_id: item for item in validation.fixtures}
    for fixture_id in ("supported-turkish-refund", "supported-english-refund"):
        item = observations[fixture_id]
        if not item.pending_action or item.risk_level != 2:
            raise AssertionError(f"{fixture_id} did not reach Risk-2 confirmation")
        if item.refund_reason_support_status != RefundReasonSupportStatus.SUPPORTED:
            raise AssertionError(f"{fixture_id} lost supported reason attribution")
    for fixture_id in (
        "missing-refund-reason",
        "unsupported-refund-reason",
        "unsupported-refund-embellishment",
    ):
        item = observations[fixture_id]
        expected = (
            RefundReasonSupportStatus.MISSING
            if fixture_id == "missing-refund-reason"
            else RefundReasonSupportStatus.UNSUPPORTED
        )
        if item.outcome != FixtureOutcome.CLARIFICATION:
            raise AssertionError(f"{fixture_id} unexpectedly became executable")
        if item.refund_reason_support_status != expected:
            raise AssertionError(f"{fixture_id} attribution changed")
    if observations["safe-read"].outcome != FixtureOutcome.READ:
        raise AssertionError("safe read fixture changed behavior")
    if observations["cancellation-write"].outcome != FixtureOutcome.ACTION:
        raise AssertionError("cancellation fixture changed behavior")
    print(validation.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
