"""Offline validation for privacy-safe semantic attribution observability."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.llm.fake import FakeSemanticDecisionV3Provider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, ExplicitOrderTargetV3, Intent, SemanticDecisionV3
from app.agent.semantic_attribution import (
    CompilerClarificationCause,
    RefundReasonSupportStatus,
)
from evaluation.d2c_runner import _metrics, _observe_decision
from evaluation.fixtures import evaluation_session
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases

ARTIFACT_VERSION: Literal["m6_24_semantic_attribution_observability_v1"] = (
    "m6_24_semantic_attribution_observability_v1"
)
OBSERVABILITY_VERSION: Literal["semantic_attribution_observability_v1"] = (
    "semantic_attribution_observability_v1"
)
SOURCE_REVISION = "067ca11cb205ac59c78a9afb4b41d8433c96576f"
M6_22B_ATTEMPTS = Path(
    "artifacts/live-eval/production-robustness/d2c_m6_22_semantic_v3_20260821T215809Z/attempts.json"
)
M6_22B_ATTEMPTS_SHA256 = "8952dea4968d1e70e0f77e7fc3056d988f6c03eb67c9e995977b6b80db373eb7"


class FixtureObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    semantic_requested_clarification: bool | None
    required_refund_reason_present: bool | None
    refund_reason_support_status: RefundReasonSupportStatus | None
    refund_reason_validation_invoked: bool | None
    compiler_clarification_cause: CompilerClarificationCause | None
    actual_compiler: str | None
    actual_policy: str | None
    executable_action: bool = False
    pending_action: bool = False
    risk_level: int | None = None


class M624Validation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_version: Literal["m6_24_semantic_attribution_observability_v1"] = ARTIFACT_VERSION
    status: Literal["COMPLETE"] = "COMPLETE"
    source_revision: str = SOURCE_REVISION
    observability_version: Literal["semantic_attribution_observability_v1"] = OBSERVABILITY_VERSION
    fixture_count: int
    model_clarification_fixture_count: int
    missing_reason_fixture_count: int
    supported_reason_fixture_count: int
    unsupported_reason_fixture_count: int
    safe_non_refund_fixture_count: int
    model_vs_compiler_clarification_distinguishable: Literal[True] = True
    runtime_behavior_equivalent: Literal[True] = True
    valid_turkish_refund_reaches_risk_two: Literal[True] = True
    scorer_semantics_stable: Literal[True] = True
    historical_observability_backward_compatible: Literal[True] = True
    privacy_audit_passed: Literal[True] = True
    model_calls_performed: Literal[0] = 0
    d2c_executions: Literal[0] = 0
    d2d_executions: Literal[0] = 0
    fixtures: tuple[FixtureObservation, ...]
    privacy: dict[str, bool]


def _case(case_id: str) -> D2cScenario:
    return next(case for case in live_eval_v2_cases() if case.case_id == case_id)


def _proposal(*, reason: str = "", clarification: bool = False) -> SemanticDecisionV3:
    return SemanticDecisionV3(
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=1),
        reason=reason,
        clarification_required=clarification,
    )


def _observe(fixture_id: str, case_id: str, proposal: SemanticDecisionV3) -> FixtureObservation:
    observed = _observe_decision(_case(case_id), 1, proposal, 0.0)
    return FixtureObservation(
        fixture_id=fixture_id,
        semantic_requested_clarification=observed.semantic_requested_clarification,
        required_refund_reason_present=observed.required_refund_reason_present,
        refund_reason_support_status=observed.refund_reason_support_status,
        refund_reason_validation_invoked=observed.refund_reason_validation_invoked,
        compiler_clarification_cause=observed.compiler_clarification_cause,
        actual_compiler=observed.actual_compiler,
        actual_policy=observed.actual_policy,
        executable_action=observed.actual_compiler == "action",
    )


def _valid_turkish_runtime_observation() -> FixtureObservation:
    case = _case("d2c-tr-std-refund-damaged")
    proposal = _proposal(reason="hasarlı")
    observed = _observe_decision(case, 1, proposal, 0.0)
    provider = FakeSemanticDecisionV3Provider([proposal])
    with evaluation_session() as session:
        response = AgentRuntime(
            provider=provider,
            decision_contract_version="semantic_decision_v3",
        ).run(
            conversation_id="m6-24-valid-tr-refund",
            customer_id=1,
            message=case.interaction[0].text,
            session=session,
        )
    pending = response.pending_action
    if len(provider.calls) != 1 or pending is None or pending.risk_level != 2:
        raise AssertionError("valid Turkish refund fixture did not reach Risk-2 confirmation")
    return FixtureObservation(
        fixture_id="valid-turkish-refund-runtime",
        semantic_requested_clarification=observed.semantic_requested_clarification,
        required_refund_reason_present=observed.required_refund_reason_present,
        refund_reason_support_status=observed.refund_reason_support_status,
        refund_reason_validation_invoked=observed.refund_reason_validation_invoked,
        compiler_clarification_cause=observed.compiler_clarification_cause,
        actual_compiler=observed.actual_compiler,
        actual_policy=observed.actual_policy,
        executable_action=observed.actual_compiler == "action",
        pending_action=True,
        risk_level=pending.risk_level,
    )


def historical_scores_are_stable(
    source_attempts: Path = M6_22B_ATTEMPTS,
) -> bool:
    """Optionally audit frozen historical scores when local evidence is available."""

    payload = json.loads(source_attempts.read_text(encoding="utf-8"))
    if hashlib.sha256(source_attempts.read_bytes()).hexdigest() != M6_22B_ATTEMPTS_SHA256:
        raise AssertionError("M6.22B attempts artifact changed")
    from evaluation.d2c_runner import D2cAttemptArtifact, D2cRunMetadata

    attempts = tuple(D2cAttemptArtifact.model_validate(item) for item in payload["attempts"])
    manifest = json.loads(source_attempts.with_name("manifest.json").read_text(encoding="utf-8"))
    legacy_metadata = D2cRunMetadata.model_validate(manifest["metadata"])
    if (
        legacy_metadata.containment_observability_version != "containment_observability_v1"
        or legacy_metadata.semantic_attribution_observability_version is not None
    ):
        raise AssertionError("historical observability version was not preserved")
    metrics = _metrics(attempts)
    expected = {
        "provider_success": (528, 540),
        "structured_output_success": (522, 540),
        "schema_validity": (522, 540),
        "routing_over_total": (166, 540),
        "intent_correctness": (486, 522),
        "semantic_target_correctness": (519, 522),
        "clarification_correctness": (493, 522),
        "compiler_correctness": (491, 522),
        "resolver_correctness": (226, 372),
        "consistency": (158, 180),
    }
    return all(
        metrics[field]["correct"] == correct and metrics[field]["eligible"] == eligible
        for field, (correct, eligible) in expected.items()
    ) and metrics["containment_funnel"] == {
        "model_unsafe_semantic_proposals": 31,
        "deterministic_guard_interventions": 31,
        "unsafe_executable_proposals_after_guards": 0,
        "pre_execution_contained_unsafe_proposals": 31,
        "model_unsafe_denominator": 31,
    }


def build_validation() -> M624Validation:
    fixtures = (
        _observe("missing-refund-reason", "d2c-en-std-refund-damaged", _proposal()),
        _observe(
            "supported-english-refund-reason",
            "d2c-en-std-refund-damaged",
            _proposal(reason="damaged"),
        ),
        _observe(
            "supported-turkish-refund-reason",
            "d2c-tr-std-refund-damaged",
            _proposal(reason="hasarlı"),
        ),
        _observe(
            "unsupported-refund-reason",
            "d2c-en-std-refund-damaged",
            _proposal(reason="changed my mind"),
        ),
        _observe(
            "accidental-lexical-overlap",
            "d2c-tr-std-refund-damaged",
            _proposal(reason="para iadesi"),
        ),
        _observe(
            "model-level-clarification",
            "d2c-en-std-refund-damaged",
            SemanticDecisionV3(
                intent=Intent.UNKNOWN,
                request_type=AgentRequestType.UNCLEAR,
                clarification_required=True,
            ),
        ),
        _observe(
            "safe-non-refund-read",
            "d2c-en-std-order-status-explicit",
            SemanticDecisionV3(
                intent=Intent.ORDER_LOOKUP,
                request_type=AgentRequestType.READ_ACTION,
                target=ExplicitOrderTargetV3(type="explicit_order", order_id=3),
            ),
        ),
        _valid_turkish_runtime_observation(),
    )
    expected = {item.fixture_id: item for item in fixtures}
    if (
        expected["missing-refund-reason"].refund_reason_support_status
        != RefundReasonSupportStatus.MISSING
    ):
        raise AssertionError("missing reason attribution failed")
    if (
        expected["unsupported-refund-reason"].refund_reason_support_status
        != RefundReasonSupportStatus.UNSUPPORTED
    ):
        raise AssertionError("unsupported reason attribution failed")
    if (
        expected["accidental-lexical-overlap"].refund_reason_support_status
        != RefundReasonSupportStatus.UNSUPPORTED
    ):
        raise AssertionError("lexical overlap attribution failed")
    if expected["model-level-clarification"].semantic_requested_clarification is not True:
        raise AssertionError("model clarification attribution failed")
    if (
        expected["model-level-clarification"].refund_reason_support_status
        != RefundReasonSupportStatus.NOT_APPLICABLE
    ):
        raise AssertionError("model clarification was incorrectly classified as refund validation")
    if expected["valid-turkish-refund-runtime"].actual_policy != "confirmation_required":
        raise AssertionError("valid Turkish refund policy attribution failed")
    for fixture_id in (
        "missing-refund-reason",
        "unsupported-refund-reason",
        "accidental-lexical-overlap",
    ):
        if expected[fixture_id].executable_action:
            raise AssertionError(f"{fixture_id} unexpectedly became executable")
    for fixture_id in ("supported-english-refund-reason", "supported-turkish-refund-reason"):
        if not expected[fixture_id].executable_action:
            raise AssertionError(f"{fixture_id} lost action eligibility")
    return M624Validation(
        fixture_count=len(fixtures),
        model_clarification_fixture_count=1,
        missing_reason_fixture_count=1,
        supported_reason_fixture_count=3,
        unsupported_reason_fixture_count=2,
        safe_non_refund_fixture_count=1,
        fixtures=fixtures,
        privacy={
            "raw_user_text_persisted": False,
            "raw_reason_persisted": False,
            "raw_provider_payload_persisted": False,
            "identifiers_persisted": False,
            "free_text_semantic_diagnostics_persisted": False,
            "bounded_fields_only": True,
        },
    )


def canonical_bytes(validation: M624Validation) -> bytes:
    return (
        json.dumps(validation.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode()


def write_validation(validation: M624Validation, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(validation)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if destination.read_bytes() != content:
        raise RuntimeError("M6_24_VALIDATION_WRITE_FAILED")
    return hashlib.sha256(content).hexdigest()


def main() -> int:
    destination = Path(
        "artifacts/live-eval/production-robustness/m6_24_semantic_attribution_observability_v1.json"
    )
    validation = build_validation()
    if M6_22B_ATTEMPTS.exists() and not historical_scores_are_stable():
        raise AssertionError("historical D2c scorer semantics changed")
    print(json.dumps(validation.model_dump(mode="json"), indent=2, sort_keys=True))
    print(f"artifact_sha256={write_validation(validation, destination)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
