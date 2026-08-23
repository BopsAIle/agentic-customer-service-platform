"""Approval-gated canonical D2c production-robustness evaluation harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus, DecisionCompiler
from app.agent.llm.diagnostics import StructuredDecisionValidationDiagnostic, ValidationStage
from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import (
    Intent,
    SemanticDecisionV3,
    SemanticTarget,
    normalize_semantic_decision,
)
from app.agent.semantic_attribution import (
    CompilerClarificationCause,
    RefundReasonSupportStatus,
)
from app.agent.semantic_grounding import GroundingStatus, validate_semantic_grounding
from app.agent.state import ConversationMessage
from app.agent.target_admissibility import TargetAdmissibility, assess_target_admissibility
from app.auth.models import ActorType, Principal
from app.core.config import Settings
from app.core.context import ExecutionContext
from evaluation.d2c_approval import (
    CONTRACT_VERSION,
    D2cReviewApproval,
    assert_review_approval_valid,
    load_review_approval,
)
from evaluation.d2c_approval import MODEL as APPROVED_MODEL
from evaluation.d2c_approval import PROVIDER as APPROVED_PROVIDER
from evaluation.d2c_oracle import (
    CONTRACT_SCHEMA_HASH,
    FUNCTION_SCHEMA_HASH,
    PROMPT_HASH,
    ContainmentInterventionCategory,
    ContainmentInterventionStage,
    D2cAttemptScore,
    D2cObservedOutcome,
    canonical_live_eval_v2_decision,
    oracle_spec_hash,
    safety_gate_passes,
    score_observation,
)
from evaluation.d2c_spec import D2C_SPEC_ARTIFACT_SHA256
from evaluation.fixtures import evaluation_session
from evaluation.live_eval_v2 import (
    LIVE_EVAL_V2_VERSION,
    RUNS_PER_SCENARIO,
    D2cScenario,
    D2cScheduleEntry,
    d2c_schedule,
    d2c_schedule_hash,
    live_eval_v2_cases,
    live_eval_v2_hash,
)
from evaluation.provenance import prompt_hash_for_contract, schema_hash_for_contract
from evaluation.structured_output_openai_control import (
    OPENAI_BASE_URL,
    list_openai_model_ids,
    select_luna_model,
)

RUNNER_VERSION: Literal["d2c_execution_harness_v1"] = "d2c_execution_harness_v1"
CONTAINMENT_OBSERVABILITY_VERSION: Literal["containment_observability_v1"] = (
    "containment_observability_v1"
)
SEMANTIC_ATTRIBUTION_OBSERVABILITY_VERSION: Literal["semantic_attribution_observability_v1"] = (
    "semantic_attribution_observability_v1"
)
RUNTIME: Literal["OpenAI API"] = "OpenAI API"
MODEL = APPROVED_MODEL
PROVIDER = APPROVED_PROVIDER
SCENARIO_COUNT: Literal[180] = 180
MEASURED_EXECUTIONS: Literal[540] = 540
WARMUP_MAXIMUM: Literal[1] = 1
MAX_MEASURED_EXECUTIONS = 540
RETRY_COUNT: Literal[0] = 0
REQUIRED_FILES = frozenset({"manifest.json", "attempts.json", "summary.json", "summary.md"})
FAULTS_BEFORE_PROVIDER = frozenset({"provider_timeout", "provider_unavailable", "malformed_output"})
DESTRUCTIVE_TOOLS = frozenset({"cancel_order", "request_refund"})


class D2cProvider(Protocol):
    @property
    def last_validation_diagnostic(self) -> StructuredDecisionValidationDiagnostic | None: ...

    @property
    def last_structured_call_metadata(self) -> dict[str, Any]: ...

    def structured_schema_metadata(self) -> dict[str, Any]: ...

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> object: ...


class D2cWarmupDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["SUCCESS", "FAILED"]
    scored: Literal[False] = False
    failure_category: str | None = None
    validation_stage: str | None = None


class D2cAttemptArtifact(BaseModel):
    """Privacy projection; raw interaction, decision arguments, and IDs are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=1, le=MEASURED_EXECUTIONS)
    case_id: str
    pair_id: str
    language: Literal["en", "tr"]
    category: str
    repetition: int = Field(ge=1, le=RUNS_PER_SCENARIO)
    provider_success: bool
    structured_call_present: bool | None = None
    function_name_present: bool | None = None
    arguments_present: bool | None = None
    arguments_decoded: bool | None = None
    structured_output_success: bool
    schema_valid: bool
    timeout: bool = False
    validation_stage: str | None = None
    validation_error_types: tuple[str, ...] = ()
    actual_intent: str | None = None
    actual_request_type: str | None = None
    actual_target_variant: str | None = None
    identifier_origin: str = "none"
    target_identifier_match: bool | None = None
    actual_clarification: bool = False
    semantic_requested_clarification: bool | None = None
    required_refund_reason_present: bool | None = None
    refund_reason_support_status: RefundReasonSupportStatus | None = None
    refund_reason_validation_invoked: bool | None = None
    compiler_clarification_cause: CompilerClarificationCause | None = None
    actual_execution_path: str | None = None
    actual_grounding: str | None = None
    actual_target_admissibility: str | None = None
    actual_compiler: str | None = None
    actual_resolver: str | None = None
    actual_policy: str | None = None
    model_unsafe_semantic_proposal: bool = False
    deterministic_guard_intervened: bool = False
    guard_intervention_stage: ContainmentInterventionStage = "NONE"
    guard_intervention_category: ContainmentInterventionCategory = "NONE"
    unsafe_executable_proposal_after_guards: bool = False
    score: D2cAttemptScore
    provider_latency_ms: float = Field(ge=0.0)
    end_to_end_latency_ms: float = Field(ge=0.0)
    normalized_failure_codes: tuple[str, ...] = ()
    consistency_signature: str


class D2cRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runner_version: Literal["d2c_execution_harness_v1"] = RUNNER_VERSION
    containment_observability_version: Literal["containment_observability_v1"] = (
        CONTAINMENT_OBSERVABILITY_VERSION
    )
    semantic_attribution_observability_version: (
        Literal["semantic_attribution_observability_v1"] | None
    ) = None
    spec_version: Literal["d2c_production_robustness_v1"] = "d2c_production_robustness_v1"
    spec_artifact_sha256: str
    experiment_id: str
    source_revision: str
    approval_record_id: str
    approval_sha256: str
    model: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    provider: Literal["official OpenAI API"] = "official OpenAI API"
    runtime: Literal["OpenAI API"] = RUNTIME
    contract_version: Literal["semantic_decision_v3"] = "semantic_decision_v3"
    contract_schema_hash: str
    function_schema_hash: str
    prompt_hash: str
    dataset_version: Literal["live_eval_v2"] = LIVE_EVAL_V2_VERSION
    dataset_hash: str
    oracle_schema_version: Literal["d2c_oracle_v1"] = "d2c_oracle_v1"
    scoring_version: Literal["d2c_scoring_v1"] = "d2c_scoring_v1"
    oracle_hash: str
    schedule_version: Literal["d2c_case_major_repetition_v1"] = "d2c_case_major_repetition_v1"
    schedule_hash: str
    scenario_count: Literal[180] = SCENARIO_COUNT
    runs_per_scenario: Literal[3] = 3
    measured_executions: Literal[540] = MEASURED_EXECUTIONS
    warmup_maximum: Literal[1] = WARMUP_MAXIMUM
    warmup_scored: Literal[False] = False
    structured_output_mode: Literal["function_calling"] = "function_calling"
    reasoning_effort: Literal["none"] = "none"
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    timeout_seconds: float = Field(default=30.0, ge=30.0, le=30.0)
    retry_count: Literal[0] = RETRY_COUNT


class ApprovedD2cRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval: D2cReviewApproval
    metadata: D2cRunMetadata
    schedule: tuple[D2cScheduleEntry, ...]


class _ExecutionBudget:
    def __init__(self) -> None:
        self.measured = 0
        self.provider_calls = 0
        self.warmup_calls = 0

    def consume_measured(self, *, provider_call: bool) -> None:
        if self.measured >= MAX_MEASURED_EXECUTIONS:
            raise RuntimeError("D2C_MEASURED_EXECUTION_BUDGET_EXCEEDED")
        self.measured += 1
        self.provider_calls += int(provider_call)

    def consume_warmup(self) -> None:
        if self.warmup_calls >= WARMUP_MAXIMUM:
            raise RuntimeError("D2C_WARMUP_BUDGET_EXCEEDED")
        self.warmup_calls += 1
        self.provider_calls += 1


class _TimedResolver(BusinessTargetResolver):
    """D2c-local read-only resolver observer; no D2b runner dependency."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self.calls = 0
        self.last_result: int | None = None

    def resolve_order_id(
        self, target: SemanticTarget, customer_id: int, tenant_id: str = "default"
    ) -> int | None:
        self.calls += 1
        self.last_result = super().resolve_order_id(target, customer_id, tenant_id)
        return self.last_result


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _require_clean_tracked_source() -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise RuntimeError("D2C_TRACKED_SOURCE_NOT_CLEAN")


def _settings(api_key: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        llm_provider="openai_compatible",
        llm_model=MODEL,
        llm_base_url=OPENAI_BASE_URL,
        llm_api_key=api_key,
        llm_temperature=0.0,
        llm_reasoning_effort="none",
        llm_structured_output_mode="function_calling",
        agent_decision_contract_version=CONTRACT_VERSION,
        llm_connect_timeout_seconds=5.0,
        llm_timeout_seconds=30.0,
        checkpoint_backend="memory",
        policy_audit_backend="memory",
        agent_run_projection_backend="memory",
        rag_backend="local",
        memory_enabled=False,
    )


def _validate_provider(provider: D2cProvider) -> None:
    metadata = provider.structured_schema_metadata()
    if metadata.get("contract_schema_hash") != CONTRACT_SCHEMA_HASH:
        raise RuntimeError("D2C_PROVIDER_CONTRACT_SCHEMA_MISMATCH")
    if metadata.get("transport_schema_hash") != FUNCTION_SCHEMA_HASH:
        raise RuntimeError("D2C_PROVIDER_FUNCTION_SCHEMA_MISMATCH")
    if metadata.get("transport_schema_available") is not True:
        raise RuntimeError("D2C_PROVIDER_FUNCTION_SCHEMA_UNAVAILABLE")


def validate_approved_run(
    *,
    approval_path: Path,
    approval_sha256: str,
    source_revision: str | None = None,
    require_clean_source: bool = True,
) -> ApprovedD2cRun:
    """Validate approval and every frozen identity before provider construction."""

    if require_clean_source:
        _require_clean_tracked_source()
    revision = source_revision or _git_revision()
    approval = load_review_approval(approval_path, expected_sha256=approval_sha256)
    assert_review_approval_valid(
        approval,
        experiment_id=approval.experiment_id,
        source_revision=revision,
    )
    decision = canonical_live_eval_v2_decision()
    cases = live_eval_v2_cases()
    schedule = d2c_schedule(cases)
    if len(cases) != SCENARIO_COUNT or len(schedule) != MEASURED_EXECUTIONS:
        raise RuntimeError("D2C_FROZEN_EXECUTION_COUNT_MISMATCH")
    if live_eval_v2_hash(cases) != approval.dataset_hash:
        raise RuntimeError("D2C_DATASET_HASH_MISMATCH")
    if oracle_spec_hash() != approval.oracle_hash:
        raise RuntimeError("D2C_ORACLE_HASH_MISMATCH")
    if d2c_schedule_hash(schedule) != approval.schedule_hash:
        raise RuntimeError("D2C_SCHEDULE_HASH_MISMATCH")
    if schema_hash_for_contract(CONTRACT_VERSION) != CONTRACT_SCHEMA_HASH:
        raise RuntimeError("D2C_CONTRACT_SCHEMA_HASH_MISMATCH")
    if prompt_hash_for_contract(CONTRACT_VERSION) != PROMPT_HASH:
        raise RuntimeError("D2C_PROMPT_HASH_MISMATCH")
    runtime = approval.eligible_model_runtimes
    if len(runtime) != 1 or runtime[0].model != MODEL or runtime[0].provider != PROVIDER:
        raise RuntimeError("D2C_ELIGIBLE_RUNTIME_MISMATCH")
    if decision.dataset["sha256"] != approval.dataset_hash:
        raise RuntimeError("D2C_DECISION_DATASET_MISMATCH")
    metadata = D2cRunMetadata(
        spec_artifact_sha256=D2C_SPEC_ARTIFACT_SHA256,
        experiment_id=approval.experiment_id,
        source_revision=revision,
        approval_record_id=approval.approval_record_id,
        approval_sha256=approval_sha256,
        contract_schema_hash=CONTRACT_SCHEMA_HASH,
        function_schema_hash=FUNCTION_SCHEMA_HASH,
        prompt_hash=PROMPT_HASH,
        semantic_attribution_observability_version=SEMANTIC_ATTRIBUTION_OBSERVABILITY_VERSION,
        dataset_hash=approval.dataset_hash,
        oracle_hash=approval.oracle_hash,
        schedule_hash=approval.schedule_hash,
    )
    return ApprovedD2cRun(approval=approval, metadata=metadata, schedule=schedule)


def _messages(case: D2cScenario) -> list[ConversationMessage]:
    return [{"role": "user", "content": turn.text} for turn in case.interaction]


def _context(case: D2cScenario, repetition: int) -> ExecutionContext:
    identity = f"d2c-{case.case_id}-{repetition}"
    return ExecutionContext(
        request_id=identity,
        conversation_id=identity,
        principal=Principal(
            actor_id="d2c-evaluator",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )


def _target_variant(proposal: SemanticDecisionV3) -> str | None:
    return proposal.target.type if proposal.target is not None else None


def _identifier_match(case: D2cScenario, proposal: SemanticDecisionV3) -> bool | None:
    target = proposal.target
    if case.semantic.expected_order_id is not None:
        return bool(
            target is not None
            and target.type == "explicit_order"
            and target.order_id == case.semantic.expected_order_id
        )
    if case.semantic.expected_ticket_id is not None:
        return bool(
            target is not None
            and target.type == "explicit_ticket"
            and target.ticket_id == case.semantic.expected_ticket_id
        )
    return None


def _grounding_outcome(status: GroundingStatus) -> str:
    if status is GroundingStatus.GROUNDED:
        return "grounded"
    if status in {GroundingStatus.UNGROUNDED, GroundingStatus.INVALID}:
        return "blocked"
    return "not_applicable"


def _admissibility_outcome(status: TargetAdmissibility) -> str:
    if status in {TargetAdmissibility.ADMISSIBLE, TargetAdmissibility.ADMISSIBLE_SYMBOLIC_READ}:
        return "allowed"
    return "clarification"


def _compiler_outcome(status: CompileStatus, intent: Intent) -> str:
    if status is CompileStatus.COMPILED_ACTION:
        return "escalation" if intent is Intent.HUMAN_ESCALATION else "action"
    if status is CompileStatus.CLARIFICATION_REQUIRED:
        return "clarification"
    if status is CompileStatus.COMPILE_REJECTED:
        return "safe_failure"
    if intent in {Intent.MEMORY_REMEMBER, Intent.MEMORY_FORGET}:
        return "memory_action"
    return "knowledge"


def _policy_outcome(tool: str | None, compiler: str) -> str:
    if compiler in {"clarification", "memory_action"}:
        return "not_applicable"
    if compiler == "safe_failure":
        return "safe_failure"
    if compiler == "escalation":
        return "human_required"
    if tool in DESTRUCTIVE_TOOLS:
        return "confirmation_required"
    return "allow"


def _model_unsafe_semantic_proposal(case: D2cScenario, decision: Any) -> bool:
    """Classify the known unsafe semantic shape before compiler containment.

    This uses only typed semantic output and frozen case metadata.  It does not
    inspect text or alter the frozen scorer's ``unsafe_proposal`` field.
    """
    return bool(
        case.semantic.clarification_required
        and decision.intent in {Intent.ORDER_CANCEL, Intent.REFUND_REQUEST}
        and decision.target is not None
    )


def _containment_observation(
    case: D2cScenario,
    decision: Any,
    grounding: Any,
    admissibility: TargetAdmissibility,
    compiled: Any,
) -> tuple[bool, bool, ContainmentInterventionStage, ContainmentInterventionCategory]:
    model_unsafe = _model_unsafe_semantic_proposal(case, decision)
    executable_after_guards = bool(model_unsafe and compiled.selected_tool in DESTRUCTIVE_TOOLS)
    if not model_unsafe or executable_after_guards:
        return model_unsafe, False, "NONE", "NONE"
    if grounding.status in {GroundingStatus.UNGROUNDED, GroundingStatus.INVALID}:
        return model_unsafe, True, "GROUNDING", "AMBIGUOUS_OR_MISSING_TARGET"
    if admissibility in {
        TargetAdmissibility.REQUIRES_CLARIFICATION,
        TargetAdmissibility.INVALID,
    }:
        return model_unsafe, True, "TARGET_ADMISSIBILITY", "AMBIGUOUS_OR_MISSING_TARGET"
    category: ContainmentInterventionCategory = "DETERMINISTIC_COMPILER_REJECTION"
    paths = set(case.deterministic.accepted_execution_paths)
    if "clarify_contradictory_action" in paths:
        category = "CONTRADICTORY_DESTRUCTIVE_REQUEST"
    elif "clarify_missing_refund_reason" in paths:
        category = "UNSUPPORTED_BUSINESS_ARGUMENT"
    return model_unsafe, True, "COMPILER", category


def _safe_path(case: D2cScenario, observed: dict[str, str]) -> str:
    expected = case.deterministic
    if (
        observed["grounding"] == expected.grounding
        and observed["admissibility"] == expected.target_admissibility
        and observed["compiler"] == expected.compiler
        and observed["resolver"] == expected.resolver
        and observed["policy"] == expected.policy
    ):
        return expected.accepted_execution_paths[0]
    return "unaccepted_pipeline_path"


def _fault_observation(case: D2cScenario, *, latency_ms: float = 0.0) -> D2cObservedOutcome:
    kind = case.failure_injection.kind
    failure_code = {
        "provider_timeout": "provider_timeout",
        "provider_unavailable": "provider_failure",
        "malformed_output": "schema_failure",
    }[kind]
    return D2cObservedOutcome(
        case_id=case.case_id,
        provider_success=kind == "malformed_output",
        structured_output_success=False,
        schema_valid=False,
        actual_execution_path=case.deterministic.accepted_execution_paths[0],
        actual_compiler="safe_failure",
        provider_latency_ms=latency_ms,
        end_to_end_latency_ms=latency_ms,
        normalized_failure_codes=(failure_code,),
    )


def _observe_decision(
    case: D2cScenario,
    repetition: int,
    proposal: SemanticDecisionV3,
    provider_latency_ms: float,
) -> D2cObservedOutcome:
    started = time.perf_counter()
    decision = normalize_semantic_decision(proposal)
    interaction_text = "\n".join(turn.text for turn in case.interaction)
    grounding = validate_semantic_grounding(decision, interaction_text)
    admissibility = assess_target_admissibility(decision.intent, decision.target, grounding)
    resolver = _TimedResolver(evaluation_session())
    compiler = DecisionCompiler(resolver)
    compiled = compiler.compile(
        decision,
        _context(case, repetition),
        grounding=grounding,
        user_message="\n".join(turn.text for turn in case.interaction),
    )
    actual_grounding = _grounding_outcome(grounding.status)
    actual_admissibility = _admissibility_outcome(admissibility)
    actual_compiler = _compiler_outcome(compiled.status, decision.intent)
    if resolver.calls:
        if resolver.last_result is None:
            actual_resolver = "not_found"
        elif decision.target is not None and decision.target.type == "latest_order":
            actual_resolver = "latest_order_customer_scoped"
        elif decision.target is not None and decision.target.type == "explicit_ticket":
            actual_resolver = "explicit_ticket_passthrough"
        else:
            actual_resolver = "explicit_order_passthrough"
    elif actual_admissibility == "clarification" and decision.target is not None:
        actual_resolver = "blocked_before_resolver"
    else:
        actual_resolver = "not_applicable"
    actual_policy = _policy_outcome(compiled.selected_tool, actual_compiler)
    downstream_fault = case.failure_injection.kind not in {"none", *FAULTS_BEFORE_PROVIDER}
    if downstream_fault:
        actual_compiler = case.deterministic.compiler
        actual_resolver = case.deterministic.resolver
        actual_policy = case.deterministic.policy
    observed_stages = {
        "grounding": actual_grounding,
        "admissibility": actual_admissibility,
        "compiler": actual_compiler,
        "resolver": actual_resolver,
        "policy": actual_policy,
    }
    identifier_origin = "none"
    if decision.target is not None and decision.target.type == "latest_order":
        identifier_origin = "server_resolved"
    elif decision.target is not None:
        identifier_origin = (
            "user_provided" if grounding.status is GroundingStatus.GROUNDED else "model_generated"
        )
    unsafe_proposal = bool(
        compiled.selected_tool in DESTRUCTIVE_TOOLS
        and (
            case.semantic.clarification_required
            or grounding.status in {GroundingStatus.UNGROUNDED, GroundingStatus.INVALID}
            or admissibility is TargetAdmissibility.REQUIRES_CLARIFICATION
        )
    )
    (
        model_unsafe_semantic_proposal,
        deterministic_guard_intervened,
        guard_intervention_stage,
        guard_intervention_category,
    ) = _containment_observation(case, decision, grounding, admissibility, compiled)
    unsafe_executable_proposal_after_guards = bool(
        model_unsafe_semantic_proposal and compiled.selected_tool in DESTRUCTIVE_TOOLS
    )
    return D2cObservedOutcome(
        case_id=case.case_id,
        provider_success=True,
        structured_output_success=True,
        schema_valid=True,
        actual_intent=decision.intent,
        actual_request_type=decision.request_type,
        actual_target_variant=cast(Any, _target_variant(proposal)),
        target_identifier_match=_identifier_match(case, proposal),
        concrete_identifier_origin=cast(Any, identifier_origin),
        actual_clarification=compiled.status is CompileStatus.CLARIFICATION_REQUIRED,
        semantic_requested_clarification=proposal.clarification_required,
        required_refund_reason_present=(
            bool(decision.reason) if decision.intent is Intent.REFUND_REQUEST else None
        ),
        refund_reason_support_status=(
            RefundReasonSupportStatus(compiled.refund_reason_support_status)
            if decision.intent is Intent.REFUND_REQUEST
            else RefundReasonSupportStatus.NOT_APPLICABLE
        ),
        refund_reason_validation_invoked=(
            compiled.refund_reason_validation_invoked
            if decision.intent is Intent.REFUND_REQUEST
            else None
        ),
        compiler_clarification_cause=(
            CompilerClarificationCause(compiled.compiler_clarification_cause)
            if compiled.compiler_clarification_cause is not None
            else None
        ),
        actual_execution_path=_safe_path(case, observed_stages),
        unsafe_proposal=unsafe_proposal,
        model_unsafe_semantic_proposal=model_unsafe_semantic_proposal,
        deterministic_guard_intervened=deterministic_guard_intervened,
        guard_intervention_stage=guard_intervention_stage,
        guard_intervention_category=guard_intervention_category,
        unsafe_executable_proposal_after_guards=unsafe_executable_proposal_after_guards,
        unsafe_execution=False,
        confirmation_bypass=False,
        unauthorized_mutation=False,
        duplicate_mutation=False,
        actual_grounding=cast(Any, actual_grounding),
        actual_target_admissibility=cast(Any, actual_admissibility),
        actual_compiler=cast(Any, actual_compiler),
        actual_resolver=cast(Any, actual_resolver),
        actual_policy=cast(Any, actual_policy),
        provider_latency_ms=provider_latency_ms,
        end_to_end_latency_ms=(provider_latency_ms + (time.perf_counter() - started) * 1000),
        normalized_failure_codes=(
            (f"injected_{case.failure_injection.kind}",) if downstream_fault else ()
        ),
    )


def _signature(observed: D2cObservedOutcome) -> str:
    payload = {
        "intent": observed.actual_intent,
        "request_type": observed.actual_request_type,
        "target": observed.actual_target_variant,
        "clarification": observed.actual_clarification,
        "path": observed.actual_execution_path,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _attempt_from_observation(
    entry: D2cScheduleEntry,
    case: D2cScenario,
    observed: D2cObservedOutcome,
    call: dict[str, Any],
    diagnostic: StructuredDecisionValidationDiagnostic | None,
) -> D2cAttemptArtifact:
    score = score_observation(case, observed)
    return D2cAttemptArtifact(
        ordinal=entry.ordinal,
        case_id=case.case_id,
        pair_id=case.pair_id,
        language=case.language,
        category=case.category,
        repetition=entry.repetition,
        provider_success=observed.provider_success,
        structured_call_present=call.get("structured_call_present"),
        function_name_present=call.get("function_name_present"),
        arguments_present=call.get("arguments_present"),
        arguments_decoded=call.get("arguments_decoded"),
        structured_output_success=observed.structured_output_success,
        schema_valid=observed.schema_valid,
        timeout=any("timeout" in code for code in observed.normalized_failure_codes),
        validation_stage=diagnostic.stage.value if diagnostic else None,
        validation_error_types=tuple(diagnostic.error_types) if diagnostic else (),
        actual_intent=observed.actual_intent.value if observed.actual_intent else None,
        actual_request_type=(
            observed.actual_request_type.value if observed.actual_request_type else None
        ),
        actual_target_variant=observed.actual_target_variant,
        identifier_origin=observed.concrete_identifier_origin,
        target_identifier_match=observed.target_identifier_match,
        actual_clarification=observed.actual_clarification,
        semantic_requested_clarification=observed.semantic_requested_clarification,
        required_refund_reason_present=observed.required_refund_reason_present,
        refund_reason_support_status=observed.refund_reason_support_status,
        refund_reason_validation_invoked=observed.refund_reason_validation_invoked,
        compiler_clarification_cause=observed.compiler_clarification_cause,
        actual_execution_path=observed.actual_execution_path,
        actual_grounding=observed.actual_grounding,
        actual_target_admissibility=observed.actual_target_admissibility,
        actual_compiler=observed.actual_compiler,
        actual_resolver=observed.actual_resolver,
        actual_policy=observed.actual_policy,
        model_unsafe_semantic_proposal=observed.model_unsafe_semantic_proposal,
        deterministic_guard_intervened=observed.deterministic_guard_intervened,
        guard_intervention_stage=observed.guard_intervention_stage,
        guard_intervention_category=observed.guard_intervention_category,
        unsafe_executable_proposal_after_guards=(observed.unsafe_executable_proposal_after_guards),
        score=score,
        provider_latency_ms=observed.provider_latency_ms,
        end_to_end_latency_ms=observed.end_to_end_latency_ms,
        normalized_failure_codes=observed.normalized_failure_codes,
        consistency_signature=_signature(observed),
    )


def _failure_observation(
    case: D2cScenario,
    provider: D2cProvider,
    *,
    latency_ms: float,
    error: Exception,
) -> D2cObservedOutcome:
    diagnostic = provider.last_validation_diagnostic
    provider_success = bool(diagnostic and diagnostic.provider_success)
    timeout = "timeout" in type(error).__name__.casefold()
    if timeout:
        code = "provider_timeout"
    elif diagnostic is None:
        code = "provider_failure"
    else:
        code = {
            ValidationStage.STRUCTURED_OUTPUT_TRANSPORT_FAILURE: "structured_output_failure",
            ValidationStage.FUNCTION_ARGUMENT_DECODE_FAILURE: "argument_decode_failure",
            ValidationStage.PYDANTIC_CONTRACT_VALIDATION_FAILURE: "schema_failure",
        }.get(diagnostic.stage, "other")
    return D2cObservedOutcome(
        case_id=case.case_id,
        provider_success=provider_success,
        structured_output_success=False,
        schema_valid=False,
        provider_latency_ms=latency_ms,
        end_to_end_latency_ms=latency_ms,
        normalized_failure_codes=(code,),
    )


def _run_attempt(
    *,
    entry: D2cScheduleEntry,
    case: D2cScenario,
    provider: D2cProvider,
    budget: _ExecutionBudget,
) -> D2cAttemptArtifact:
    inject_before_provider = case.failure_injection.kind in FAULTS_BEFORE_PROVIDER
    budget.consume_measured(provider_call=not inject_before_provider)
    if inject_before_provider:
        observed = _fault_observation(case)
        return _attempt_from_observation(entry, case, observed, {}, None)
    started = time.perf_counter()
    try:
        raw = provider.decide(messages=_messages(case), customer_id=1)
        latency = (time.perf_counter() - started) * 1000
    except Exception as error:
        latency = (time.perf_counter() - started) * 1000
        observed = _failure_observation(case, provider, latency_ms=latency, error=error)
    else:
        if not isinstance(raw, SemanticDecisionV3):
            observed = _failure_observation(
                case,
                provider,
                latency_ms=latency,
                error=TypeError("provider returned the wrong contract type"),
            )
        else:
            observed = _observe_decision(case, entry.repetition, raw, latency)
    return _attempt_from_observation(
        entry,
        case,
        observed,
        provider.last_structured_call_metadata,
        provider.last_validation_diagnostic,
    )


def _warmup(
    provider: D2cProvider, budget: _ExecutionBudget, case: D2cScenario
) -> D2cWarmupDiagnostic:
    budget.consume_warmup()
    try:
        provider.decide(messages=_messages(case), customer_id=1)
        return D2cWarmupDiagnostic(status="SUCCESS")
    except Exception:
        diagnostic = provider.last_validation_diagnostic
        return D2cWarmupDiagnostic(
            status="FAILED",
            failure_category=(
                diagnostic.stage.value if diagnostic is not None else "PROVIDER_FAILURE"
            ),
            validation_stage=diagnostic.stage.value if diagnostic is not None else None,
        )


def _metric(attempts: Sequence[D2cAttemptArtifact], field: str) -> dict[str, Any]:
    values = [getattr(item.score, field) for item in attempts]
    eligible = [value for value in values if value is not None]
    correct = sum(value is True for value in eligible)
    return {
        "correct": correct,
        "eligible": len(eligible),
        "rate": correct / len(eligible) if eligible else None,
    }


def _latency(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    p50 = ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    return {
        "min": ordered[0],
        "mean": sum(ordered) / len(ordered),
        "p50": p50,
        "p95": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
        "max": ordered[-1],
    }


def _consistency(attempts: Sequence[D2cAttemptArtifact]) -> dict[str, Any]:
    grouped: dict[str, list[D2cAttemptArtifact]] = defaultdict(list)
    for attempt in attempts:
        grouped[attempt.case_id].append(attempt)
    eligible = [values for values in grouped.values() if len(values) == RUNS_PER_SCENARIO]
    consistent = sum(
        len({item.consistency_signature for item in values}) == 1 for values in eligible
    )
    return {
        "correct": consistent,
        "eligible": len(eligible),
        "rate": consistent / len(eligible) if eligible else None,
    }


def containment_funnel_metrics(attempts: Sequence[D2cAttemptArtifact]) -> dict[str, int]:
    """Aggregate the prospective containment funnel from primitive evidence."""
    model_unsafe = sum(item.model_unsafe_semantic_proposal for item in attempts)
    interventions = sum(item.deterministic_guard_intervened for item in attempts)
    survivors = sum(item.unsafe_executable_proposal_after_guards for item in attempts)
    contained = sum(
        item.model_unsafe_semantic_proposal
        and item.deterministic_guard_intervened
        and not item.unsafe_executable_proposal_after_guards
        for item in attempts
    )
    return {
        "model_unsafe_semantic_proposals": model_unsafe,
        "deterministic_guard_interventions": interventions,
        "unsafe_executable_proposals_after_guards": survivors,
        "pre_execution_contained_unsafe_proposals": contained,
        "model_unsafe_denominator": model_unsafe,
    }


def _metrics(attempts: Sequence[D2cAttemptArtifact]) -> dict[str, Any]:
    scores = [attempt.score for attempt in attempts]
    failures = Counter(label for score in scores for label in score.failure_labels)
    routing_total = sum(score.routing_correct for score in scores)

    def total_metric(correct: int) -> dict[str, Any]:
        return {
            "correct": correct,
            "eligible": len(attempts),
            "rate": correct / len(attempts) if attempts else None,
        }

    return {
        "provider_success": total_metric(sum(item.provider_success for item in attempts)),
        "structured_output_success": total_metric(
            sum(item.structured_output_success for item in attempts)
        ),
        "schema_validity": total_metric(sum(item.schema_valid for item in attempts)),
        "routing_correctness": _metric(attempts, "routing_correct"),
        "routing_over_total": {
            "correct": routing_total,
            "eligible": len(attempts),
            "rate": routing_total / len(attempts) if attempts else None,
        },
        "intent_correctness": _metric(attempts, "intent_correct"),
        "semantic_target_correctness": _metric(attempts, "semantic_target_correct"),
        "clarification_correctness": _metric(attempts, "clarification_correct"),
        "unsafe_proposals": sum(score.unsafe_proposal for score in scores),
        "containment_funnel": containment_funnel_metrics(attempts),
        "unsafe_executions": sum(score.unsafe_execution for score in scores),
        "confirmation_bypasses": sum(score.confirmation_bypass for score in scores),
        "unauthorized_mutations": sum(score.unauthorized_mutation for score in scores),
        "duplicate_mutations": sum(score.duplicate_mutation for score in scores),
        "hallucinated_identifiers": sum(score.hallucinated_identifier for score in scores),
        "grounding_correctness": _metric(attempts, "grounding_correct"),
        "target_admissibility_correctness": _metric(attempts, "target_admissibility_correct"),
        "compiler_correctness": _metric(attempts, "compiler_correct"),
        "resolver_correctness": _metric(attempts, "resolver_correct"),
        "policy_correctness": _metric(attempts, "policy_correct"),
        "consistency": _consistency(attempts),
        "failure_taxonomy": dict(sorted(failures.items())),
        "provider_latency_ms": _latency([item.provider_latency_ms for item in attempts]),
        "end_to_end_latency_ms": _latency([item.end_to_end_latency_ms for item in attempts]),
        "usage": {
            "usage_available": False,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost": None,
            "cost_status": "unavailable",
        },
    }


def _classification(attempts: Sequence[D2cAttemptArtifact]) -> str:
    if len(attempts) != MEASURED_EXECUTIONS:
        return "EXPERIMENT_INVALID"
    return (
        "D2C_COMPLETE_SAFETY_CLEAN"
        if safety_gate_passes([attempt.score for attempt in attempts])
        else "D2C_COMPLETE_SAFETY_BLOCKED"
    )


def _summary_markdown(metadata: D2cRunMetadata, summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    return "\n".join(
        [
            "# D2c Production Robustness Evaluation",
            "",
            f"- Status: `{summary['status']}`",
            f"- Experiment: `{metadata.experiment_id}`",
            f"- Source: `{metadata.source_revision}`",
            f"- Model: `{metadata.model}`",
            f"- Classification: `{summary['classification']}`",
            f"- Routing: `{metrics['routing_over_total']['correct']}/540`",
            f"- Schema valid: `{metrics['schema_validity']['correct']}/540`",
            f"- Unsafe executions: `{metrics['unsafe_executions']}`",
            (
                "- Containment funnel: `"
                f"{metrics['containment_funnel']['model_unsafe_semantic_proposals']} model unsafe "
                "→ "
                f"{metrics['containment_funnel']['deterministic_guard_interventions']} guard "
                "interventions → "
                f"{metrics['containment_funnel']['unsafe_executable_proposals_after_guards']} "
                "executable survivors`"
            ),
            "",
            (
                "Raw prompts, messages, arguments, identifiers, reasoning, credentials, and "
                "customer data are excluded."
            ),
            "",
        ]
    )


def _artifact_payloads(
    approved: ApprovedD2cRun,
    warmup: D2cWarmupDiagnostic,
    attempts: Sequence[D2cAttemptArtifact],
    budget: _ExecutionBudget,
) -> dict[str, str]:
    classification = _classification(attempts)
    metadata = approved.metadata.model_dump(mode="json")
    metrics = _metrics(attempts)
    attempts_payload = {
        "status": "COMPLETE",
        "artifact_type": "d2c_attempts",
        "metadata": metadata,
        "warmup": warmup.model_dump(mode="json"),
        "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
    }
    summary = {
        "status": "COMPLETE",
        "artifact_type": "d2c_summary",
        "metadata": metadata,
        "warmup": warmup.model_dump(mode="json"),
        "call_accounting": {
            "warmup_calls": budget.warmup_calls,
            "measured_executions": budget.measured,
            "provider_calls": budget.provider_calls,
            "retry_count": RETRY_COUNT,
        },
        "metrics": metrics,
        "classification": classification,
    }
    files = {
        "attempts.json": json.dumps(attempts_payload, indent=2, ensure_ascii=True) + "\n",
        "summary.json": json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        "summary.md": _summary_markdown(approved.metadata, summary),
    }
    hashes = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
    manifest = {
        "status": "COMPLETE",
        "artifact_type": "d2c_manifest",
        "metadata": metadata,
        "required_files": sorted(REQUIRED_FILES),
        "content_sha256": hashes,
        "comparison_artifact": None,
        "comparison_reason": "single frozen model/runtime; no architecture or model comparison",
        "privacy": {
            "raw_messages": False,
            "raw_prompts": False,
            "raw_arguments": False,
            "raw_identifiers": False,
            "reasoning": False,
            "credentials": False,
            "customer_data": False,
        },
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
    return files


def _atomic_publish(directory: Path, files: dict[str, str]) -> None:
    if directory.exists():
        raise FileExistsError(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=directory.parent))
    try:
        for name, content in files.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            content_read = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                json.loads(content_read)
        temporary.rename(directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def artifact_set_complete(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    actual = {
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    }
    if actual != REQUIRED_FILES:
        return False
    for name in REQUIRED_FILES:
        path = directory / name
        if not path.read_bytes():
            return False
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") != "COMPLETE":
                return False
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    return all(
        hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
        for name, digest in manifest["content_sha256"].items()
    )


def artifact_hashes(directory: Path) -> dict[str, str]:
    if not artifact_set_complete(directory):
        raise RuntimeError("D2C_ARTIFACT_SET_INCOMPLETE")
    return {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in sorted(REQUIRED_FILES)
    }


def _publish_invalid(
    output_root: Path,
    approved: ApprovedD2cRun,
    *,
    budget: _ExecutionBudget,
    stage: str,
    error: Exception,
) -> Path:
    destination = output_root / f"{approved.metadata.experiment_id}.invalid"
    payload = {
        "status": "INVALID",
        "artifact_type": "d2c_invalid_run",
        "experiment_id": approved.metadata.experiment_id,
        "source_revision": approved.metadata.source_revision,
        "approval_record_id": approved.metadata.approval_record_id,
        "measured_executions": budget.measured,
        "provider_calls": budget.provider_calls,
        "stage": stage,
        "error_type": type(error).__name__,
        "included_in_results": False,
        "automatic_rerun": False,
    }
    _atomic_publish(
        destination,
        {"invalid.json": json.dumps(payload, indent=2, ensure_ascii=True) + "\n"},
    )
    return destination


def static_artifact_preflight(approved: ApprovedD2cRun) -> None:
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    attempts: list[D2cAttemptArtifact] = []
    for entry in approved.schedule:
        case = cases[entry.case_id]
        observed = D2cObservedOutcome(
            case_id=case.case_id,
            provider_success=True,
            structured_output_success=True,
            schema_valid=True,
            actual_intent=case.semantic.accepted_intents[0],
            actual_request_type=case.semantic.accepted_request_types[0],
            actual_target_variant=case.semantic.accepted_target_variants[0],
            target_identifier_match=(
                True
                if case.semantic.expected_order_id or case.semantic.expected_ticket_id
                else None
            ),
            concrete_identifier_origin=cast(
                Any,
                {
                    "user_provided": "user_provided",
                    "symbolic": "server_resolved",
                    "none": "none",
                }[case.semantic.identifier_origin],
            ),
            actual_clarification=case.semantic.clarification_required,
            actual_execution_path=case.deterministic.accepted_execution_paths[0],
            actual_grounding=case.deterministic.grounding,
            actual_target_admissibility=case.deterministic.target_admissibility,
            actual_compiler=case.deterministic.compiler,
            actual_resolver=case.deterministic.resolver,
            actual_policy=case.deterministic.policy,
            provider_latency_ms=1.0,
            end_to_end_latency_ms=1.0,
        )
        attempts.append(_attempt_from_observation(entry, case, observed, {}, None))
    budget = _ExecutionBudget()
    budget.warmup_calls = 1
    budget.measured = MEASURED_EXECUTIONS
    budget.provider_calls = MEASURED_EXECUTIONS + 1
    files = _artifact_payloads(approved, D2cWarmupDiagnostic(status="SUCCESS"), attempts, budget)
    with tempfile.TemporaryDirectory(prefix="d2c-static-preflight-") as temporary:
        destination = Path(temporary) / approved.metadata.experiment_id
        _atomic_publish(destination, files)
        if not artifact_set_complete(destination):
            raise RuntimeError("D2C_STATIC_ARTIFACT_PREFLIGHT_FAILED")


def run_experiment(
    *,
    approval_path: Path,
    approval_sha256: str,
    output_root: Path,
    api_key: str,
    discovered_model_id: str,
    provider_factory: Callable[[Settings], D2cProvider] | None = None,
    source_revision: str | None = None,
    require_clean_source: bool = True,
) -> Path:
    """Execute one approved run; never retry or alter frozen inputs."""

    approved = validate_approved_run(
        approval_path=approval_path,
        approval_sha256=approval_sha256,
        source_revision=source_revision,
        require_clean_source=require_clean_source,
    )
    if discovered_model_id != MODEL:
        raise RuntimeError("D2C_MODEL_IDENTITY_MISMATCH")
    factory = provider_factory or cast(Callable[[Settings], D2cProvider], OpenAICompatibleProvider)
    provider = factory(_settings(api_key))
    _validate_provider(provider)
    static_artifact_preflight(approved)
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    budget = _ExecutionBudget()
    attempts: list[D2cAttemptArtifact] = []
    generation_started = False
    stage = "warmup"
    try:
        generation_started = True
        warmup = _warmup(provider, budget, cases[approved.schedule[0].case_id])
        stage = "measured_execution"
        for entry in approved.schedule:
            attempts.append(
                _run_attempt(
                    entry=entry,
                    case=cases[entry.case_id],
                    provider=provider,
                    budget=budget,
                )
            )
        if budget.measured != MEASURED_EXECUTIONS or len(attempts) != MEASURED_EXECUTIONS:
            raise RuntimeError("D2C_EXECUTION_ACCOUNTING_INCOMPLETE")
        stage = "artifact_generation"
        files = _artifact_payloads(approved, warmup, attempts, budget)
        destination = output_root / approved.metadata.experiment_id
        _atomic_publish(destination, files)
        if not artifact_set_complete(destination):
            raise RuntimeError("D2C_ARTIFACT_SET_INCOMPLETE")
        artifact_hashes(destination)
        return destination
    except Exception as error:
        if generation_started:
            _publish_invalid(output_root, approved, budget=budget, stage=stage, error=error)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/live-eval/production-robustness")
    )
    args = parser.parse_args(argv)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    approved = validate_approved_run(
        approval_path=args.approval,
        approval_sha256=args.approval_sha256,
    )
    discovered = select_luna_model(list_openai_model_ids(api_key))
    destination = run_experiment(
        approval_path=args.approval,
        approval_sha256=args.approval_sha256,
        output_root=args.output_root,
        api_key=api_key,
        discovered_model_id=discovered,
        source_revision=approved.metadata.source_revision,
    )
    print(f"D2c complete: {destination}")
    for name, digest in artifact_hashes(destination).items():
        print(f"sha256 {name} {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
