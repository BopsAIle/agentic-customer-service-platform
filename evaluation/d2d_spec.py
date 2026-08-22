"""Immutable, non-executing contract for the D2d operational release gate."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

D2D_CONTRACT_VERSION = "d2d_release_candidate_operational_v1"
D2D_ARTIFACT_SCHEMA_VERSION = "d2d_release_candidate_artifact_v1"
D2D_SCHEDULE_VERSION = "d2d_release_candidate_operational_schedule_v1"
D2D_FAULT_MATRIX_VERSION = "d2d_release_candidate_operational_faults_v1"
D2D_ALEMBIC_HEAD = "20260812_0007"

D2D_CONTRACT_SHA256 = "ebe77e28973a6314a3892ce896994c8e3897cd87ccf60e27ab5d1f1f8b8e0aa0"
D2D_SCHEDULE_SHA256 = "d79a0bdd5cf9390feb57a795c38131c07b40977295be80744ac494616b1fc582"
D2D_FAULT_MATRIX_SHA256 = "7c7591deff962343d2fe5288c8b3bd9e97557c8cf9a94975bb76c160630378b9"

D2D_PHASE_IDS = (
    "D2D-0_ENVIRONMENT_FREEZE",
    "D2D-1_CLEAN_BOOTSTRAP",
    "D2D-2_BASELINE_FUNCTIONAL_E2E",
    "D2D-3_CONCURRENCY_IDEMPOTENCY",
    "D2D-4_RESTART_PERSISTENCE",
    "D2D-5_FAILURE_RECOVERY",
    "D2D-6_OBSERVABILITY_PRIVACY",
    "D2D-7_FINAL_INTEGRITY",
)

D2D_SCENARIO_IDS = (
    "clean-bootstrap",
    "readiness-mandatory-dependencies",
    "baseline-safe-read",
    "baseline-risk2-confirmation",
    "baseline-risk3-escalation",
    "same-action-concurrency",
    "independent-action-concurrency",
    "pending-confirmation-restart",
    "completed-action-replay-restart",
    "declined-confirmation-restart",
    "stale-confirmation-restart",
    "unknown-write-ack-recovery",
    "postgres-unavailable",
    "qdrant-unavailable",
    "provider-timeout",
    "provider-malformed-output",
    "otel-collector-unavailable",
    "observability-privacy-scan",
)

D2D_ZERO_TOLERANCE_FAILURES = (
    "migration_failure",
    "application_not_ready",
    "unsafe_executable_action",
    "confirmation_bypass",
    "unauthorized_mutation",
    "duplicate_mutation",
    "stale_confirmation_resurrection",
    "declined_confirmation_resurrection",
    "same_action_multiple_committed_effects",
    "persistence_corruption_after_restart",
    "mandatory_dependency_not_recovered",
    "required_observability_evidence_missing",
    "privacy_violation",
    "malformed_or_incomplete_artifacts",
    "source_or_configuration_drift",
)


class D2dPhase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_id: str = Field(pattern=r"^D2D-[0-7]_[A-Z0-9_]+$")
    purpose: str = Field(min_length=1)
    mandatory: Literal[True] = True


class D2dScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    phase_id: str
    purpose: str = Field(min_length=1)
    execution_mode: Literal["EXISTING_INTERFACE", "HARNESS_REQUIRED"]
    mandatory: Literal[True] = True


class D2dFault(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fault_id: str = Field(min_length=1)
    injection_boundary: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    recovery_assertion: str = Field(min_length=1)
    execution_mode: Literal["EXISTING_INTERFACE", "HARNESS_REQUIRED"]
    mandatory: Literal[True] = True


class D2dContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["d2d_release_candidate_operational_v1"] = (
        "d2d_release_candidate_operational_v1"
    )
    artifact_schema_version: Literal["d2d_release_candidate_artifact_v1"] = (
        "d2d_release_candidate_artifact_v1"
    )
    purpose: Literal["END_TO_END_RELEASE_CANDIDATE_OPERATIONAL_VALIDATION"] = (
        "END_TO_END_RELEASE_CANDIDATE_OPERATIONAL_VALIDATION"
    )
    deployment_scope: Literal["PRODUCTION_ORIENTED_SINGLE_ENVIRONMENT_REFERENCE_DEPLOYMENT"]
    provider_requirement: Literal["NOT_APPLICABLE_CORE"] = "NOT_APPLICABLE_CORE"
    environment: dict[str, object]
    non_goals: tuple[str, ...]
    phases: tuple[D2dPhase, ...]
    scenarios: tuple[D2dScenario, ...]
    concurrency: dict[str, object]
    fault_matrix_version: Literal["d2d_release_candidate_operational_faults_v1"] = (
        "d2d_release_candidate_operational_faults_v1"
    )
    fault_matrix: tuple[D2dFault, ...]
    recovery_policy: dict[str, object]
    observability_requirements: tuple[str, ...]
    privacy_requirements: tuple[str, ...]
    authority_safety_invariants: tuple[str, ...]
    zero_tolerance_failures: tuple[str, ...]
    artifact_contract: dict[str, object]
    retry_policy: dict[str, object]
    approval_bindings: tuple[str, ...]
    entry_criteria: tuple[str, ...]
    scope_decisions: dict[str, object]
    final_classifications: tuple[str, ...]

    @model_validator(mode="after")
    def validate_frozen_contract(self) -> D2dContract:
        if tuple(phase.phase_id for phase in self.phases) != D2D_PHASE_IDS:
            raise ValueError("D2D_PHASE_ORDER_MISMATCH")
        if tuple(scenario.scenario_id for scenario in self.scenarios) != D2D_SCENARIO_IDS:
            raise ValueError("D2D_SCENARIO_ORDER_MISMATCH")
        if tuple(fault.fault_id for fault in self.fault_matrix) != (
            "postgres-unavailable",
            "qdrant-unavailable",
            "provider-timeout",
            "provider-malformed-output",
            "otel-collector-unavailable",
            "unknown-write-ack-failure",
        ):
            raise ValueError("D2D_FAULT_MATRIX_ORDER_MISMATCH")
        if self.concurrency != {
            "same_action_concurrent_attempts": 16,
            "same_action_rounds": 3,
            "same_action_success_invariant": (
                "exactly_one_committed_business_effect_per_round; "
                "all_other_contenders resolve safely"
            ),
            "independent_action_count": 2,
            "independent_action_rounds": 3,
            "capacity_or_throughput_claim": False,
        }:
            raise ValueError("D2D_CONCURRENCY_CONTRACT_MISMATCH")
        if self.retry_policy != {
            "per_test_automatic_retry_count": 0,
            "automatic_full_run_rerun_count": 0,
            "patch_and_continue": False,
            "invalid_run_requires_new_approval": True,
        }:
            raise ValueError("D2D_RETRY_POLICY_MISMATCH")
        expected_artifact_contract = {
            "publication": "atomic_new_directory_no_overwrite",
            "raw_container_logs_canonical": False,
            "sha256_each_file": True,
            "partial_run_status": "INVALID_NOT_COMPLETE",
        }
        raw_artifact_files = self.artifact_contract.get("files", ())
        artifact_files: tuple[object, ...] = (
            tuple(raw_artifact_files) if isinstance(raw_artifact_files, (list, tuple)) else ()
        )
        if (
            artifact_files
            != (
                "manifest.json",
                "environment.json",
                "attempts.json",
                "summary.json",
                "summary.md",
            )
            or {key: value for key, value in self.artifact_contract.items() if key != "files"}
            != expected_artifact_contract
        ):
            raise ValueError("D2D_ARTIFACT_CONTRACT_MISMATCH")
        if self.zero_tolerance_failures != D2D_ZERO_TOLERANCE_FAILURES:
            raise ValueError("D2D_ZERO_TOLERANCE_MISMATCH")
        if "D2D_RELEASE_GATE_PASS" not in self.final_classifications:
            raise ValueError("D2D_PASS_CLASSIFICATION_MISSING")
        return self


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))).encode(
        "utf-8"
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def canonical_d2d_contract() -> D2dContract:
    """Return the D2d contract without starting containers or making provider calls."""

    return D2dContract(
        deployment_scope="PRODUCTION_ORIENTED_SINGLE_ENVIRONMENT_REFERENCE_DEPLOYMENT",
        environment={
            "checkout": "clean tracked checkout",
            "deployment": "docker compose with docker-compose.integration.yml override",
            "services": ("db", "qdrant", "demo-setup", "backend", "frontend", "jaeger"),
            "database": "PostgreSQL",
            "retrieval": "Qdrant",
            "observability": "OpenTelemetry to Jaeger",
            "llm_provider": "deterministic_integration",
            "openai_model_list_calls": 0,
            "openai_inference_calls": 0,
            "ambient_dotenv": "ignored; dedicated frozen environment required",
            "identities": "deterministic integration seed and isolated volumes",
            "alembic_head": D2D_ALEMBIC_HEAD,
            "downgrade_policy": "UNDEFINED",
        },
        non_goals=(
            "model benchmarking",
            "prompt tuning",
            "RAG quality benchmarking",
            "another 540-case semantic benchmark",
            "large-scale throughput certification",
            "capacity planning",
            "multi-region operation",
            "Kubernetes production certification",
            "Terraform or cloud infrastructure",
            "enterprise OIDC or managed IAM validation",
            "public Internet TLS termination",
            "SOC2, GDPR, or HIPAA certification",
            "exact provider cost accounting",
            "voice, multi-agent workflows, or new business tools",
        ),
        phases=tuple(
            D2dPhase(phase_id=phase_id, purpose=purpose)
            for phase_id, purpose in zip(
                D2D_PHASE_IDS,
                (
                    "freeze source, configuration, services, images, and contract identity",
                    "migrate a fresh database, seed/bootstrap, and establish readiness",
                    "exercise deployed safe-read, Risk-2, and supported escalation flows",
                    "prove same-action idempotency and independent-action concurrency correctness",
                    "prove pending, completed, declined, and stale confirmation restart behavior",
                    "exercise selected dependency failures and state-based recovery",
                    "verify bounded traces, operational evidence, and privacy-safe artifacts",
                    "recompute identities, invariants, hashes, and the strict final gate",
                ),
                strict=True,
            )
        ),
        scenarios=tuple(
            D2dScenario(
                scenario_id=scenario_id,
                phase_id=phase_id,
                purpose=purpose,
                execution_mode=execution_mode,
            )
            for scenario_id, phase_id, purpose, execution_mode in (
                (
                    "clean-bootstrap",
                    "D2D-1_CLEAN_BOOTSTRAP",
                    "fresh volumes migrate, seed, ingest, and start the reference stack",
                    "EXISTING_INTERFACE",
                ),
                (
                    "readiness-mandatory-dependencies",
                    "D2D-1_CLEAN_BOOTSTRAP",
                    "health and readiness reflect mandatory dependency state",
                    "EXISTING_INTERFACE",
                ),
                (
                    "baseline-safe-read",
                    "D2D-2_BASELINE_FUNCTIONAL_E2E",
                    "deployed safe read remains functional",
                    "EXISTING_INTERFACE",
                ),
                (
                    "baseline-risk2-confirmation",
                    "D2D-2_BASELINE_FUNCTIONAL_E2E",
                    "Risk-2 proposal, confirmation, persistence, and mutation complete",
                    "EXISTING_INTERFACE",
                ),
                (
                    "baseline-risk3-escalation",
                    "D2D-2_BASELINE_FUNCTIONAL_E2E",
                    "supported escalation persists its bounded outcome",
                    "EXISTING_INTERFACE",
                ),
                (
                    "same-action-concurrency",
                    "D2D-3_CONCURRENCY_IDEMPOTENCY",
                    "sixteen contenders race the same confirmed action in three rounds",
                    "HARNESS_REQUIRED",
                ),
                (
                    "independent-action-concurrency",
                    "D2D-3_CONCURRENCY_IDEMPOTENCY",
                    "two independent valid actions run concurrently for three rounds",
                    "HARNESS_REQUIRED",
                ),
                (
                    "pending-confirmation-restart",
                    "D2D-4_RESTART_PERSISTENCE",
                    "unexpired pending confirmation survives backend restart and executes once",
                    "EXISTING_INTERFACE",
                ),
                (
                    "completed-action-replay-restart",
                    "D2D-4_RESTART_PERSISTENCE",
                    "completed action replay after restart has no duplicate effect",
                    "EXISTING_INTERFACE",
                ),
                (
                    "declined-confirmation-restart",
                    "D2D-4_RESTART_PERSISTENCE",
                    "declined action remains non-executable after restart",
                    "EXISTING_INTERFACE",
                ),
                (
                    "stale-confirmation-restart",
                    "D2D-4_RESTART_PERSISTENCE",
                    "expired or stale action remains non-executable after restart",
                    "HARNESS_REQUIRED",
                ),
                (
                    "unknown-write-ack-recovery",
                    "D2D-5_FAILURE_RECOVERY",
                    "unknown write acknowledgement does not create a duplicate mutation",
                    "HARNESS_REQUIRED",
                ),
                (
                    "postgres-unavailable",
                    "D2D-5_FAILURE_RECOVERY",
                    "database loss is explicit, fail-safe, and recoverable after restoration",
                    "EXISTING_INTERFACE",
                ),
                (
                    "qdrant-unavailable",
                    "D2D-5_FAILURE_RECOVERY",
                    "retrieval degradation follows existing semantics without gaining authority",
                    "EXISTING_INTERFACE",
                ),
                (
                    "provider-timeout",
                    "D2D-5_FAILURE_RECOVERY",
                    "deterministic provider timeout maps to safe existing failure behavior",
                    "EXISTING_INTERFACE",
                ),
                (
                    "provider-malformed-output",
                    "D2D-5_FAILURE_RECOVERY",
                    "malformed output is classified and cannot authorize unsafe execution",
                    "EXISTING_INTERFACE",
                ),
                (
                    "otel-collector-unavailable",
                    "D2D-5_FAILURE_RECOVERY",
                    "non-critical telemetry loss does not become business authority",
                    "EXISTING_INTERFACE",
                ),
                (
                    "observability-privacy-scan",
                    "D2D-6_OBSERVABILITY_PRIVACY",
                    "representative traces and artifacts are bounded and privacy-safe",
                    "EXISTING_INTERFACE",
                ),
            )
        ),
        concurrency={
            "same_action_concurrent_attempts": 16,
            "same_action_rounds": 3,
            "same_action_success_invariant": (
                "exactly_one_committed_business_effect_per_round; "
                "all_other_contenders resolve safely"
            ),
            "independent_action_count": 2,
            "independent_action_rounds": 3,
            "capacity_or_throughput_claim": False,
        },
        fault_matrix=(
            D2dFault(
                fault_id="postgres-unavailable",
                injection_boundary="PostgreSQL dependency unavailable",
                expected_behavior="readiness not_ready; no unsafe write execution",
                recovery_assertion=(
                    "after restoration readiness recovers and a subsequent safe request succeeds"
                ),
                execution_mode="EXISTING_INTERFACE",
            ),
            D2dFault(
                fault_id="qdrant-unavailable",
                injection_boundary="Qdrant retrieval dependency unavailable",
                expected_behavior="existing retrieval degradation semantics; no authority gain",
                recovery_assertion=(
                    "after restoration readiness/retrieval returns to the existing healthy behavior"
                ),
                execution_mode="EXISTING_INTERFACE",
            ),
            D2dFault(
                fault_id="provider-timeout",
                injection_boundary="deterministic provider timeout fixture",
                expected_behavior="existing safe provider-failure taxonomy and no unsafe action",
                recovery_assertion="subsequent request succeeds after fault removal",
                execution_mode="EXISTING_INTERFACE",
            ),
            D2dFault(
                fault_id="provider-malformed-output",
                injection_boundary="deterministic malformed structured-output fixture",
                expected_behavior="existing malformed-output taxonomy and no unsafe action",
                recovery_assertion="subsequent valid request succeeds after fault removal",
                execution_mode="EXISTING_INTERFACE",
            ),
            D2dFault(
                fault_id="otel-collector-unavailable",
                injection_boundary="OTLP collector unavailable",
                expected_behavior="application remains safe; telemetry is non-authoritative",
                recovery_assertion="business state remains coherent and later telemetry can resume",
                execution_mode="EXISTING_INTERFACE",
            ),
            D2dFault(
                fault_id="unknown-write-ack-failure",
                injection_boundary="business write acknowledgement/response boundary",
                expected_behavior="unknown outcome is not blindly replayed",
                recovery_assertion=(
                    "reconciliation or idempotent retry yields at most one committed effect"
                ),
                execution_mode="HARNESS_REQUIRED",
            ),
        ),
        recovery_policy={
            "state_based_assertions_only": True,
            "timing_slo": "TIMING_SLO_NOT_PART_OF_D2D_V1",
            "mandatory_dependency_restoration_required": True,
            "corrupted_pending_action_forbidden": True,
        },
        observability_requirements=(
            "safe-read trace is retrievable",
            "Risk-2 trace includes correlation, policy, confirmation, and execution state",
            "blocked or guarded flow includes bounded intervention and failure category",
            "failure/recovery trace includes dependency and recovery classification",
            "no raw prompt, response, reasoning, or business payload is required",
        ),
        privacy_requirements=(
            "published D2d privacy violations must equal zero",
            "operational IDs use existing bounded privacy-safe conventions",
            "raw user text, raw model payloads, secrets, memory, and RAG content are prohibited",
        ),
        authority_safety_invariants=(
            "LLM/provider remains non-authoritative",
            "no unauthorized customer-scoped write",
            "no confirmation bypass or unconfirmed Risk-2 mutation",
            "no direct Risk-3 mutation when escalation is required",
            "no duplicate business mutation",
            "no stale or declined confirmation resurrection",
            "no server-owned identifier override",
            "memory and RAG content do not gain executable authority",
        ),
        zero_tolerance_failures=D2D_ZERO_TOLERANCE_FAILURES,
        artifact_contract={
            "files": (
                "manifest.json",
                "environment.json",
                "attempts.json",
                "summary.json",
                "summary.md",
            ),
            "publication": "atomic_new_directory_no_overwrite",
            "raw_container_logs_canonical": False,
            "sha256_each_file": True,
            "partial_run_status": "INVALID_NOT_COMPLETE",
        },
        retry_policy={
            "per_test_automatic_retry_count": 0,
            "automatic_full_run_rerun_count": 0,
            "patch_and_continue": False,
            "invalid_run_requires_new_approval": True,
        },
        approval_bindings=(
            "experiment_id",
            "exact source revision",
            "d2d contract version and SHA",
            "environment/configuration identity",
            "container/image identities",
            "Alembic head",
            "scenario schedule SHA",
            "concurrency parameters",
            "fault matrix identity",
            "artifact schema/version",
            "retry and rerun policy",
        ),
        entry_criteria=(
            "source equals the approved release candidate",
            "D2c remains CLOSED_FOR_CURRENT_RELEASE_CANDIDATE",
            "M6.29B evidence integrity is valid",
            "D2d contract SHA is valid",
            "D2d contract tests pass",
            "clean deployment environment is available",
            "Docker/container prerequisites are available",
            "configuration is isolated from developer .env",
            "required dependency images/services are available",
            "no uncommitted tracked source changes",
            "approval binds exact scenario, fault, and concurrency contract",
        ),
        scope_decisions={
            "full_load_benchmarking": "POST_RC_HARDENING",
            "exact_llm_cost_accounting": "NON_BLOCKING_POST_RC_HARDENING",
            "managed_cloud_deployment": "V2_SCOPE",
            "enterprise_iam_tls": "V2_SCOPE",
            "multi_region_ha": "V2_SCOPE",
            "chaos_and_long_soak": "POST_RC_HARDENING",
            "migration_downgrade_gate": "UNDEFINED_NOT_A_D2D_V1_PASS_CRITERION",
        },
        final_classifications=(
            "D2D_RELEASE_GATE_PASS",
            "D2D_PRODUCT_SAFETY_FAILURE",
            "D2D_CONCURRENCY_IDEMPOTENCY_FAILURE",
            "D2D_PERSISTENCE_RECOVERY_FAILURE",
            "D2D_DEPLOYMENT_READINESS_FAILURE",
            "D2D_OBSERVABILITY_PRIVACY_FAILURE",
            "D2D_EXECUTION_INVALID_OR_INCOMPLETE",
        ),
    )


def canonical_schedule_payload(contract: D2dContract | None = None) -> dict[str, object]:
    selected = contract or canonical_d2d_contract()
    return {
        "version": D2D_SCHEDULE_VERSION,
        "scenario_ids": [scenario.scenario_id for scenario in selected.scenarios],
        "phase_ids": list(D2D_PHASE_IDS),
        "same_action_rounds": selected.concurrency["same_action_rounds"],
        "independent_action_rounds": selected.concurrency["independent_action_rounds"],
    }


def canonical_fault_matrix_payload(contract: D2dContract | None = None) -> dict[str, object]:
    selected = contract or canonical_d2d_contract()
    return {
        "version": D2D_FAULT_MATRIX_VERSION,
        "faults": [fault.model_dump(mode="json") for fault in selected.fault_matrix],
    }


def d2d_schedule_sha256(contract: D2dContract | None = None) -> str:
    return _sha256(canonical_schedule_payload(contract))


def d2d_fault_matrix_sha256(contract: D2dContract | None = None) -> str:
    return _sha256(canonical_fault_matrix_payload(contract))


def d2d_contract_sha256(contract: D2dContract | None = None) -> str:
    selected = contract or canonical_d2d_contract()
    return _sha256(selected.model_dump(mode="json"))


def validate_contract_identity(contract: D2dContract | None = None) -> None:
    selected = contract or canonical_d2d_contract()
    if d2d_schedule_sha256(selected) != D2D_SCHEDULE_SHA256:
        raise RuntimeError("D2D_SCHEDULE_HASH_MISMATCH")
    if d2d_fault_matrix_sha256(selected) != D2D_FAULT_MATRIX_SHA256:
        raise RuntimeError("D2D_FAULT_MATRIX_HASH_MISMATCH")
    if d2d_contract_sha256(selected) != D2D_CONTRACT_SHA256:
        raise RuntimeError("D2D_CONTRACT_HASH_MISMATCH")
