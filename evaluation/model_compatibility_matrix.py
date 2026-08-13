"""D2a SemanticDecisionV3 model/runtime compatibility funnel."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import SemanticDecisionV3
from app.core.config import Settings
from evaluation.live_cases import (
    LIVE_CASE_SET_V1_1_VERSION,
    LIVE_CASE_SET_V1_2_VERSION,
    LiveEvalCase,
    live_cases_v1_1,
    live_cases_v1_2,
)
from evaluation.live_scoring import case_set_metadata
from evaluation.provenance import (
    build_provenance,
    prompt_hash_for_contract,
    schema_hash_for_contract,
)
from evaluation.structured_output_diagnostics import (
    DIAGNOSTIC_CASE_IDS,
    RUNS_PER_CASE,
    DiagnosticAttempt,
    _run_attempt,
)
from evaluation.structured_output_openai_control import CountingProvider, GenerationCallBudget
from evaluation.structured_output_v3_gate import (
    CONTRACT_VERSION,
    GATE_SCHEMA_VERSION,
    GateRunStatus,
    _atomic_publish,
    _require_clean_tracked_worktree,
    _summary,
    _target_branch_requirements,
    artifact_set_complete,
)

D2A_GATE_SCHEMA_VERSION = "d2a_candidate_gate_v1"
D2A_MATRIX_SCHEMA_VERSION = "d2a_compatibility_matrix_v1"
ELIGIBILITY_RULE_VERSION = "d2a_compatibility_gate_v1"
EXPECTED_SOURCE_REVISION = "7e556eac6b159aa46d06d3b993a0fa28663c15de"
EXPECTED_SCHEMA_HASH = "b0c7c1ddb1fe4423b528f7ce05fbc63fa117737c797149f5903d327a8de6280b"
EXPECTED_FUNCTION_SCHEMA_HASH = "49ad87926db3b66c183000da65f528008b2021d0c040e76218a5e4c3318d2fc1"
EXPECTED_PROMPT_HASH = "4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0"
EXPECTED_V1_1_HASH = "ad00fd8120e8c5187f667ee95ae7c93c387ed371f168af9d2cd76bb34631bd08"
EXPECTED_V1_2_HASH = "d8a10741dbb90e8a4de3b09098de36c4969c0b72944d253e37c9580279064eb5"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
MEASURED_ATTEMPTS = len(DIAGNOSTIC_CASE_IDS) * RUNS_PER_CASE
MAX_GENERATION_CALLS = 1 + MEASURED_ATTEMPTS
REQUIRED_RUN_FILES = frozenset({"attempts.json", "summary.json", "summary.md"})
REQUIRED_MATRIX_FILES = frozenset(
    {"manifest.json", "compatibility_matrix.json", "compatibility_matrix.md"}
)


class EvidenceOrigin(StrEnum):
    REUSED = "REUSED_CANONICAL_EVIDENCE"
    NEW = "NEW_D2A_RUN"
    UNAVAILABLE = "UNAVAILABLE"


class Eligibility(StrEnum):
    ELIGIBLE = "D2A_ELIGIBLE"
    REVIEW = "D2A_REVIEW_REQUIRED"
    INELIGIBLE = "D2A_INELIGIBLE"
    UNAVAILABLE = "D2A_UNAVAILABLE"
    INVALID = "EXPERIMENT_INVALID"


class HistoricalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostic_id: str
    attempts_sha256: str = Field(min_length=64, max_length=64)
    summary_sha256: str = Field(min_length=64, max_length=64)
    markdown_sha256: str = Field(min_length=64, max_length=64)


class ModelCompatibilityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    display_name: str
    provider: Literal["openai", "ollama"]
    requested_model: str
    expected_model_family: str
    role: str
    historical_evidence: HistoricalEvidence | None = None


class LocalModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tag: str
    digest: str
    quantization: str | None
    ollama_version: str | None
    platform_architecture: str | None


class WarmupStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class WarmupDiagnostic(BaseModel):
    """Privacy-safe, unscored outcome of the single warmup generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: WarmupStatus
    generation_calls: Literal[1] = 1
    failure_category: str | None = None
    validation_stage: str | None = None
    provider_success: bool
    structured_call_present: bool | None = None
    function_name_present: bool | None = None
    arguments_present: bool | None = None
    arguments_decoded: bool | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> WarmupDiagnostic:
        if self.status is WarmupStatus.SUCCESS and (
            self.failure_category is not None or self.validation_stage is not None
        ):
            raise ValueError("successful warmup cannot contain failure metadata")
        if self.status is WarmupStatus.FAILED and self.failure_category is None:
            raise ValueError("failed warmup requires a normalized failure category")
        return self


class D2aRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostic_id: str
    diagnostic_schema_version: str = D2A_GATE_SCHEMA_VERSION
    source_revision: str = Field(min_length=40, max_length=40)
    candidate_id: str
    provider: Literal["ollama"]
    model: str
    model_digest: str
    quantization: str | None
    runtime: Literal["Ollama"] = "Ollama"
    runtime_version: str | None
    platform_architecture: str | None
    decision_contract_version: str = CONTRACT_VERSION
    decision_schema_hash: str
    function_schema_hash: str
    prompt_hash: str
    dataset_version: str = LIVE_CASE_SET_V1_2_VERSION
    case_set_hash: str
    targeted_subset_hash: str
    structured_output_mode: Literal["function_calling"] = "function_calling"
    reasoning_effort: Literal["none"] = "none"
    temperature: float = 0.0
    timeout_seconds: float = 30.0
    retry_count: int = 0
    runs_per_case: int = RUNS_PER_CASE
    measured_attempts: int = MEASURED_ATTEMPTS
    warmup_count: int = 1
    warmup: WarmupDiagnostic
    selected_case_ids: tuple[str, ...] = DIAGNOSTIC_CASE_IDS

    @model_validator(mode="after")
    def validate_frozen_protocol(self) -> D2aRunMetadata:
        if self.diagnostic_schema_version != D2A_GATE_SCHEMA_VERSION:
            raise ValueError("diagnostic schema version mismatch")
        if self.decision_contract_version != CONTRACT_VERSION:
            raise ValueError("decision contract mismatch")
        if self.decision_schema_hash != EXPECTED_SCHEMA_HASH:
            raise ValueError("decision schema hash mismatch")
        if self.function_schema_hash != EXPECTED_FUNCTION_SCHEMA_HASH:
            raise ValueError("function schema hash mismatch")
        if self.prompt_hash != EXPECTED_PROMPT_HASH:
            raise ValueError("prompt hash mismatch")
        if self.case_set_hash != EXPECTED_V1_2_HASH:
            raise ValueError("dataset hash mismatch")
        if self.targeted_subset_hash != targeted_subset_hash(live_cases_v1_2()):
            raise ValueError("targeted subset hash mismatch")
        if self.dataset_version != LIVE_CASE_SET_V1_2_VERSION:
            raise ValueError("dataset version mismatch")
        if (
            self.temperature != 0.0
            or self.timeout_seconds != 30.0
            or self.retry_count != 0
            or self.runs_per_case != RUNS_PER_CASE
            or self.measured_attempts != MEASURED_ATTEMPTS
            or self.warmup_count != 1
            or self.selected_case_ids != DIAGNOSTIC_CASE_IDS
        ):
            raise ValueError("D2a request methodology mismatch")
        return self


class D2aRunArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[GateRunStatus.COMPLETE] = GateRunStatus.COMPLETE
    metadata: D2aRunMetadata
    provenance: dict[str, Any]
    transport_schema: dict[str, Any]
    attempts: list[DiagnosticAttempt]
    summary: dict[str, Any]


class CompatibilityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate: str
    provider_runtime: str
    exact_model_tag: str | None
    digest: str | None
    quantization: str | None
    runtime_version: str | None
    evidence_origin: EvidenceOrigin
    diagnostic_id: str | None
    provider_success: int | None
    structured_call_success: int | None
    function_name_present: int | None
    arguments_present: int | None
    arguments_decoded: int | None
    typed_semantic_decision_v3: int | None
    typed_percentage: float | None
    validation_failures: int | None
    timeouts: int | None
    dominant_failure_class: str | None
    en_typed: int | None
    tr_typed: int | None
    latency_ms: dict[str, float] | None
    eligibility: Eligibility
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)


class CompatibilityMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[GateRunStatus.COMPLETE] = GateRunStatus.COMPLETE
    matrix_schema_version: str = D2A_MATRIX_SCHEMA_VERSION
    d2a_id: str
    source_revision: str
    decision_contract_version: str = CONTRACT_VERSION
    decision_schema_hash: str
    function_schema_hash: str
    prompt_hash: str
    dataset_version: str = LIVE_CASE_SET_V1_2_VERSION
    dataset_hash: str
    targeted_subset_hash: str
    eligibility_rule_version: str = ELIGIBILITY_RULE_VERSION
    rows: list[CompatibilityRow]
    d2b_eligible_candidates: list[str]
    d2b_review_candidates: list[str]
    ineligible_candidates: list[str]
    unavailable_candidates: list[str]
    readiness: str


def candidate_manifest() -> tuple[ModelCompatibilityCandidate, ...]:
    return (
        ModelCompatibilityCandidate(
            candidate_id="gpt_5_6_luna",
            display_name="GPT-5.6 Luna",
            provider="openai",
            requested_model="gpt-5.6-luna",
            expected_model_family="gpt-5.6-luna",
            role="high_compatibility_hosted_reference_control",
            historical_evidence=HistoricalEvidence(
                diagnostic_id="structured_output_v3_openai_luna_20260813T163700Z",
                attempts_sha256=(
                    "ca29727e949580e2261d707d8e9d7d1b25b9358a921dca6a3fcf34030834e7bd"
                ),
                summary_sha256=("28cd194448f9513068e03b435611bd292da257f9b38969e49b8ea4e9b8169b4d"),
                markdown_sha256=(
                    "2e690ed6a63db87d698d27e6f011212cfd7d2fb0e0effceffbc38c1630c94562"
                ),
            ),
        ),
        ModelCompatibilityCandidate(
            candidate_id="qwen3_5_4b",
            display_name="Qwen3.5 4B",
            provider="ollama",
            requested_model="qwen3.5:4b",
            expected_model_family="qwen3.5:4b",
            role="known_low_compatibility_local_baseline",
            historical_evidence=HistoricalEvidence(
                diagnostic_id="structured_output_v3_qwen3_5_4b_20260813T163044Z",
                attempts_sha256=(
                    "952b0d6684f159a51722cd3c11022acfa0c8a3b9d7555c85288933effbe8a81a"
                ),
                summary_sha256=("bc393be492185a402081a2a4a1aeba4371ca5bbfcd1476465088a63655e5b693"),
                markdown_sha256=(
                    "77f6f467584bf88c7b49a31af2a1d98b690fffe08be7c5c89b851e25086543ad"
                ),
            ),
        ),
        ModelCompatibilityCandidate(
            candidate_id="qwen2_5_7b_instruct",
            display_name="Qwen2.5 7B Instruct",
            provider="ollama",
            requested_model="qwen2.5:7b-instruct",
            expected_model_family="qwen2.5:7b-instruct",
            role="new_v3_compatibility_candidate",
        ),
        ModelCompatibilityCandidate(
            candidate_id="qwen3_5_9b",
            display_name="Qwen3.5 9B",
            provider="ollama",
            requested_model="qwen3.5:9b",
            expected_model_family="qwen3.5:9b",
            role="stronger_local_runtime_budget_candidate",
        ),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def targeted_subset_payload(cases: Sequence[LiveEvalCase]) -> list[dict[str, Any]]:
    by_id = {case.id: case for case in cases}
    missing = [case_id for case_id in DIAGNOSTIC_CASE_IDS if case_id not in by_id]
    if missing:
        raise ValueError(f"targeted cases missing: {', '.join(missing)}")
    return [by_id[case_id].model_dump(mode="json") for case_id in DIAGNOSTIC_CASE_IDS]


def targeted_subset_hash(cases: Sequence[LiveEvalCase]) -> str:
    encoded = json.dumps(
        targeted_subset_payload(cases), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_subset_equivalence() -> tuple[str, str]:
    v1_1 = targeted_subset_hash(live_cases_v1_1())
    v1_2 = targeted_subset_hash(live_cases_v1_2())
    if targeted_subset_payload(live_cases_v1_1()) != targeted_subset_payload(live_cases_v1_2()):
        raise RuntimeError("D2A_TARGETED_SUBSET_DRIFT")
    return v1_1, v1_2


def _fixed_contract_preflight() -> None:
    if schema_hash_for_contract(CONTRACT_VERSION) != EXPECTED_SCHEMA_HASH:
        raise RuntimeError("D2A_SCHEMA_HASH_DRIFT")
    if prompt_hash_for_contract(CONTRACT_VERSION) != EXPECTED_PROMPT_HASH:
        raise RuntimeError("D2A_PROMPT_HASH_DRIFT")
    v1_1 = case_set_metadata(live_cases_v1_1(), version=LIVE_CASE_SET_V1_1_VERSION)
    v1_2 = case_set_metadata(live_cases_v1_2(), version=LIVE_CASE_SET_V1_2_VERSION)
    if v1_1["sha256"] != EXPECTED_V1_1_HASH or v1_2["sha256"] != EXPECTED_V1_2_HASH:
        raise RuntimeError("D2A_DATASET_HASH_DRIFT")
    provider = OpenAICompatibleProvider(_local_settings("preflight-model"))
    schema = provider.structured_schema_metadata()
    if schema["transport_schema_hash"] != EXPECTED_FUNCTION_SCHEMA_HASH:
        raise RuntimeError("D2A_FUNCTION_SCHEMA_HASH_DRIFT")
    validate_subset_equivalence()


def _timeout_count(attempts: Sequence[DiagnosticAttempt]) -> int:
    return sum("timeout" in (attempt.error_type or "").casefold() for attempt in attempts)


def _dominant_failure(summary: dict[str, Any], timeouts: int) -> str | None:
    if timeouts:
        return "timeout"
    normalized = summary["failure_taxonomy"]["normalized_errors"]
    if normalized:
        return str(max(sorted(normalized), key=lambda item: normalized[item]))
    error_types = summary.get("by_error_type", {})
    if error_types:
        return str(max(sorted(error_types), key=lambda item: error_types[item]))
    return None


def eligibility_for(
    *,
    provider_success: int,
    arguments_decoded: int,
    typed_success: int,
    timeout_count: int,
    failure_taxonomy: dict[str, Any],
    experiment_valid: bool = True,
) -> Eligibility:
    if not experiment_valid:
        return Eligibility.INVALID
    normalized: dict[str, int] = failure_taxonomy.get("normalized_errors", {})
    transport = int(failure_taxonomy.get("transport_failures", 0))
    decode = int(failure_taxonomy.get("argument_decode_failures", 0))
    fundamental_shape = sum(
        count
        for signature, count in normalized.items()
        if "model_attributes_type@target" in signature
        or "model_type@<root>" in signature
        or "missing@target" in signature
    )
    if (
        typed_success <= 20
        or provider_success <= 20
        or timeout_count >= 2
        or transport >= 3
        or decode >= 3
        or fundamental_shape >= 3
    ):
        return Eligibility.INELIGIBLE
    if (
        provider_success >= 23
        and arguments_decoded >= 23
        and typed_success >= 23
        and timeout_count <= 1
        and transport < 2
        and decode < 2
        and fundamental_shape < 3
    ):
        return Eligibility.ELIGIBLE
    return Eligibility.REVIEW


def _row_from_evidence(
    *,
    candidate: ModelCompatibilityCandidate,
    origin: EvidenceOrigin,
    diagnostic_id: str,
    metadata: dict[str, Any],
    attempts: list[DiagnosticAttempt],
    summary: dict[str, Any],
    artifact_paths: dict[str, str],
    artifact_hashes: dict[str, str],
) -> CompatibilityRow:
    timeouts = _timeout_count(attempts)
    typed = int(summary["typed_decision_success"])
    eligibility = eligibility_for(
        provider_success=int(summary["provider_success"]),
        arguments_decoded=int(summary["arguments_decoded"]),
        typed_success=typed,
        timeout_count=timeouts,
        failure_taxonomy=summary["failure_taxonomy"],
    )
    return CompatibilityRow(
        candidate_id=candidate.candidate_id,
        candidate=candidate.display_name,
        provider_runtime=("OpenAI API" if candidate.provider == "openai" else "Ollama"),
        exact_model_tag=str(metadata["model"]),
        digest=metadata.get("model_digest"),
        quantization=metadata.get("quantization"),
        runtime_version=metadata.get("runtime_version"),
        evidence_origin=origin,
        diagnostic_id=diagnostic_id,
        provider_success=int(summary["provider_success"]),
        structured_call_success=int(summary["structured_call_present"]),
        function_name_present=int(summary["function_name_present"]),
        arguments_present=int(summary["arguments_present"]),
        arguments_decoded=int(summary["arguments_decoded"]),
        typed_semantic_decision_v3=typed,
        typed_percentage=round(typed / MEASURED_ATTEMPTS * 100, 2),
        validation_failures=int(summary["validation_failures"]),
        timeouts=timeouts,
        dominant_failure_class=_dominant_failure(summary, timeouts),
        en_typed=int(summary["by_language"]["en"]["typed_decision_success"]),
        tr_typed=int(summary["by_language"]["tr"]["typed_decision_success"]),
        latency_ms=summary["latency_ms"],
        eligibility=eligibility,
        artifact_paths=artifact_paths,
        artifact_hashes=artifact_hashes,
    )


def import_historical_evidence(
    candidate: ModelCompatibilityCandidate, artifact_root: Path
) -> CompatibilityRow:
    evidence = candidate.historical_evidence
    if evidence is None:
        raise ValueError("candidate has no historical evidence")
    directory = artifact_root / evidence.diagnostic_id
    paths = {
        "attempts.json": directory / "attempts.json",
        "summary.json": directory / "summary.json",
        "summary.md": directory / "summary.md",
    }
    expected = {
        "attempts.json": evidence.attempts_sha256,
        "summary.json": evidence.summary_sha256,
        "summary.md": evidence.markdown_sha256,
    }
    if any(not path.is_file() for path in paths.values()):
        raise FileNotFoundError(directory)
    actual = {name: _sha256(path) for name, path in paths.items()}
    if actual != expected:
        raise RuntimeError(f"HISTORICAL_ARTIFACT_HASH_MISMATCH:{candidate.candidate_id}")
    attempts_payload = json.loads(paths["attempts.json"].read_text(encoding="utf-8"))
    summary_payload = json.loads(paths["summary.json"].read_text(encoding="utf-8"))
    if attempts_payload.get("status") != "COMPLETE" or summary_payload.get("status") != "COMPLETE":
        raise RuntimeError("HISTORICAL_EVIDENCE_NOT_COMPLETE")
    metadata = attempts_payload["metadata"]
    if metadata != summary_payload["metadata"]:
        raise RuntimeError("HISTORICAL_METADATA_MISMATCH")
    exact = {
        "diagnostic_id": evidence.diagnostic_id,
        "diagnostic_schema_version": GATE_SCHEMA_VERSION,
        "decision_contract_version": CONTRACT_VERSION,
        "decision_schema_hash": EXPECTED_SCHEMA_HASH,
        "function_schema_hash": EXPECTED_FUNCTION_SCHEMA_HASH,
        "prompt_hash": EXPECTED_PROMPT_HASH,
        "dataset_version": LIVE_CASE_SET_V1_1_VERSION,
        "case_set_hash": EXPECTED_V1_1_HASH,
        "model": candidate.requested_model,
        "provider": candidate.provider,
        "structured_output_mode": "function_calling",
        "reasoning_effort": "none",
        "temperature": 0.0,
        "timeout_seconds": 30.0,
        "retry_count": 0,
        "runs_per_case": 3,
        "measured_attempts": 24,
        "warmup_count": 1,
        "selected_case_ids": list(DIAGNOSTIC_CASE_IDS),
    }
    for key, value in exact.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"HISTORICAL_METADATA_DRIFT:{key}")
    transport = attempts_payload["transport_schema"]
    if transport.get("transport_schema_hash") != EXPECTED_FUNCTION_SCHEMA_HASH:
        raise RuntimeError("HISTORICAL_TRANSPORT_SCHEMA_DRIFT")
    attempts = [DiagnosticAttempt.model_validate(item) for item in attempts_payload["attempts"]]
    if len(attempts) != MEASURED_ATTEMPTS:
        raise RuntimeError("HISTORICAL_ATTEMPT_COUNT_MISMATCH")
    recomputed = _summary(attempts)
    if recomputed != summary_payload["summary"]:
        raise RuntimeError("HISTORICAL_DIAGNOSTIC_INTERPRETATION_DRIFT")
    runtime_version = attempts_payload["provenance"]["runtime"].get("runtime_version")
    if candidate.candidate_id == "qwen3_5_4b":
        if metadata.get("model_digest") != (
            "2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
        ):
            raise RuntimeError("HISTORICAL_QWEN_DIGEST_DRIFT")
        if metadata.get("quantization") != "Q4_K_M":
            raise RuntimeError("HISTORICAL_QWEN_QUANTIZATION_DRIFT")
        if runtime_version != "ollama version is 0.32.6":
            raise RuntimeError("HISTORICAL_QWEN_RUNTIME_DRIFT")
    elif attempts_payload["provenance"]["model"].get("inference_hardware") != "provider_managed":
        raise RuntimeError("HISTORICAL_LUNA_PROVIDER_PROVENANCE_DRIFT")
    normalized_metadata = dict(metadata)
    normalized_metadata["runtime_version"] = runtime_version
    return _row_from_evidence(
        candidate=candidate,
        origin=EvidenceOrigin.REUSED,
        diagnostic_id=evidence.diagnostic_id,
        metadata=normalized_metadata,
        attempts=attempts,
        summary=recomputed,
        artifact_paths={name: str(path) for name, path in paths.items()},
        artifact_hashes=actual,
    )


def discover_local_model(
    model_tag: str,
    *,
    base_url: str = OLLAMA_BASE_URL,
    get: Callable[..., httpx.Response] = httpx.get,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LocalModelIdentity | None:
    tags_url = base_url.rstrip("/")
    if tags_url.endswith("/v1"):
        tags_url = tags_url[:-3]
    try:
        response = get(f"{tags_url}/api/tags", timeout=5.0)
        response.raise_for_status()
        models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    model = next(
        (item for item in models if isinstance(item, dict) and item.get("name") == model_tag), None
    )
    if not isinstance(model, dict) or not isinstance(model.get("digest"), str):
        return None
    raw_details = model.get("details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    try:
        version = runner(
            ["ollama", "--version"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        version = None
    return LocalModelIdentity(
        tag=model_tag,
        digest=model["digest"],
        quantization=details.get("quantization_level"),
        ollama_version=version or None,
        platform_architecture=platform.machine() or None,
    )


def _local_settings(model: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        llm_provider="openai_compatible",
        llm_model=model,
        llm_base_url=OLLAMA_BASE_URL,
        llm_api_key=None,
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


def _run_metadata(
    candidate: ModelCompatibilityCandidate,
    diagnostic_id: str,
    identity: LocalModelIdentity,
    source_revision: str,
    provider: OpenAICompatibleProvider,
    warmup: WarmupDiagnostic,
) -> D2aRunMetadata:
    return D2aRunMetadata(
        diagnostic_id=diagnostic_id,
        source_revision=source_revision,
        candidate_id=candidate.candidate_id,
        provider="ollama",
        model=identity.tag,
        model_digest=identity.digest,
        quantization=identity.quantization,
        runtime_version=identity.ollama_version,
        platform_architecture=identity.platform_architecture,
        decision_schema_hash=EXPECTED_SCHEMA_HASH,
        function_schema_hash=str(provider.structured_schema_metadata()["transport_schema_hash"]),
        prompt_hash=EXPECTED_PROMPT_HASH,
        case_set_hash=EXPECTED_V1_2_HASH,
        targeted_subset_hash=targeted_subset_hash(live_cases_v1_2()),
        warmup=warmup,
    )


def _run_markdown(artifact: D2aRunArtifact) -> str:
    metadata = artifact.metadata
    summary = artifact.summary
    return "\n".join(
        [
            "# D2a Semantic V3 Compatibility Gate",
            "",
            f"- Status: `{artifact.status}`",
            f"- Diagnostic: `{metadata.diagnostic_id}`",
            f"- Candidate: `{metadata.candidate_id}`",
            f"- Model: `{metadata.model}`",
            f"- Contract: `{metadata.decision_contract_version}`",
            f"- Dataset: `{metadata.dataset_version}`",
            f"- Targeted subset: `{metadata.targeted_subset_hash}`",
            f"- Warmup: `{metadata.warmup.status}`",
            f"- Warmup failure: `{metadata.warmup.failure_category or 'none'}`",
            f"- Typed decisions: `{summary['typed_decision_success']}/24`",
            f"- Eligibility: `{summary['d2a_eligibility']}`",
            "",
            "## Failure taxonomy",
            "",
            "```json",
            json.dumps(summary["failure_taxonomy"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )


def _run_files(artifact: D2aRunArtifact) -> dict[str, str]:
    attempts = {
        "status": artifact.status,
        "metadata": artifact.metadata.model_dump(mode="json"),
        "provenance": artifact.provenance,
        "transport_schema": artifact.transport_schema,
        "attempts": [attempt.model_dump(mode="json") for attempt in artifact.attempts],
    }
    summary = {
        "status": artifact.status,
        "metadata": artifact.metadata.model_dump(mode="json"),
        "summary": artifact.summary,
    }
    return {
        "attempts.json": json.dumps(attempts, indent=2, ensure_ascii=False) + "\n",
        "summary.json": json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        "summary.md": _run_markdown(artifact),
    }


def publish_run(artifact: D2aRunArtifact, output_root: Path) -> Path:
    destination = output_root / artifact.metadata.diagnostic_id
    _atomic_publish(destination, _run_files(artifact))
    if not artifact_set_complete(destination, REQUIRED_RUN_FILES):
        raise RuntimeError("D2A_RUN_ARTIFACT_INCOMPLETE")
    return destination


def _provenance(metadata: D2aRunMetadata) -> dict[str, Any]:
    args = argparse.Namespace(
        model=metadata.model,
        base_url=OLLAMA_BASE_URL,
        structured_output_mode="function_calling",
        reasoning_effort="none",
        temperature=0.0,
        timeout=30.0,
    )
    provenance = build_provenance(
        args=args,
        case_set_version=metadata.dataset_version,
        case_set_hash=metadata.case_set_hash,
        prompt_hash=metadata.prompt_hash,
        scoring_version=metadata.diagnostic_schema_version,
        runs_per_case=metadata.runs_per_case,
        unique_cases=len(metadata.selected_case_ids),
        total_attempts=metadata.measured_attempts,
        decision_contract_version=metadata.decision_contract_version,
    )
    provenance["model"].update(
        {
            "model_digest": metadata.model_digest,
            "quantization": metadata.quantization,
        }
    )
    provenance["runtime"]["runtime_version"] = metadata.runtime_version
    provenance["hardware"] = {
        "architecture": metadata.platform_architecture,
        "memory_class_bytes": provenance["hardware"].get("memory_bytes"),
        "collection_note": "Privacy-safe evaluation client metadata; inference is local.",
    }
    return provenance


def _cases_v1_2() -> dict[str, LiveEvalCase]:
    return {case.id: case for case in live_cases_v1_2()}


def _warmup_failure_category(error: Exception, validation_stage: str | None) -> str:
    if validation_stage:
        return validation_stage
    if isinstance(error, ValidationError):
        return "PYDANTIC_CONTRACT_VALIDATION_FAILURE"
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "PROVIDER_TIMEOUT"
    if isinstance(error, httpx.HTTPError):
        return "PROVIDER_TRANSPORT_FAILURE"
    return "WARMUP_GENERATION_FAILURE"


def _warmup(provider: CountingProvider, case: LiveEvalCase) -> WarmupDiagnostic:
    try:
        provider.decide(
            messages=[{"role": "user", "content": case.rendered_input()}],
            customer_id=case.customer_id,
        )
    except Exception as error:
        diagnostic = provider.last_validation_diagnostic
        metadata = provider.last_structured_call_metadata or {}
        validation_stage = diagnostic.stage.value if diagnostic is not None else None
        return WarmupDiagnostic(
            status=WarmupStatus.FAILED,
            failure_category=_warmup_failure_category(error, validation_stage),
            validation_stage=validation_stage,
            provider_success=bool(diagnostic and diagnostic.provider_success),
            structured_call_present=metadata.get("structured_call_present"),
            function_name_present=metadata.get("function_name_present"),
            arguments_present=metadata.get("arguments_present"),
            arguments_decoded=metadata.get("arguments_decoded"),
        )
    metadata = provider.last_structured_call_metadata or {}
    return WarmupDiagnostic(
        status=WarmupStatus.SUCCESS,
        provider_success=True,
        structured_call_present=metadata.get("structured_call_present"),
        function_name_present=metadata.get("function_name_present"),
        arguments_present=metadata.get("arguments_present"),
        arguments_decoded=metadata.get("arguments_decoded"),
    )


def _complete_summary(attempts: list[DiagnosticAttempt]) -> dict[str, Any]:
    summary = _summary(attempts)
    timeouts = _timeout_count(attempts)
    summary["timeout_count"] = timeouts
    summary["d2a_eligibility"] = eligibility_for(
        provider_success=int(summary["provider_success"]),
        arguments_decoded=int(summary["arguments_decoded"]),
        typed_success=int(summary["typed_decision_success"]),
        timeout_count=timeouts,
        failure_taxonomy=summary["failure_taxonomy"],
    ).value
    return summary


def synthetic_run_artifact(
    candidate: ModelCompatibilityCandidate,
    identity: LocalModelIdentity,
) -> D2aRunArtifact:
    provider = OpenAICompatibleProvider(_local_settings(identity.tag))
    metadata = _run_metadata(
        candidate,
        "synthetic-d2a-run",
        identity,
        "0" * 40,
        provider,
        WarmupDiagnostic(status=WarmupStatus.SUCCESS, provider_success=True),
    )
    attempts = [
        DiagnosticAttempt(
            case_id=case_id,
            language=_cases_v1_2()[case_id].language,
            category="preflight",
            run_index=run_index,
            contract_version=CONTRACT_VERSION,
            provider_success=True,
            typed_decision_success=True,
            structured_call_present=True,
            tool_call_count=1,
            function_name_present=True,
            arguments_present=True,
            arguments_decoded=True,
            typed_model_constructed=True,
            latency_ms=1.0,
        )
        for case_id in DIAGNOSTIC_CASE_IDS
        for run_index in range(1, 4)
    ]
    return D2aRunArtifact(
        metadata=metadata,
        provenance={"preflight": True},
        transport_schema=provider.structured_schema_metadata(),
        attempts=attempts,
        summary=_complete_summary(attempts),
    )


def static_artifact_preflight() -> None:
    candidate = candidate_manifest()[2]
    identity = LocalModelIdentity(
        tag=candidate.requested_model,
        digest="a" * 64,
        quantization="Q4_K_M",
        ollama_version="ollama version is test",
        platform_architecture="arm64",
    )
    with tempfile.TemporaryDirectory(prefix="d2a-preflight-") as temp:
        root = Path(temp)
        artifact = synthetic_run_artifact(candidate, identity)
        destination = publish_run(artifact, root)
        row = _row_from_evidence(
            candidate=candidate,
            origin=EvidenceOrigin.NEW,
            diagnostic_id=artifact.metadata.diagnostic_id,
            metadata=artifact.metadata.model_dump(mode="json"),
            attempts=artifact.attempts,
            summary=artifact.summary,
            artifact_paths={name: str(destination / name) for name in REQUIRED_RUN_FILES},
            artifact_hashes={name: _sha256(destination / name) for name in REQUIRED_RUN_FILES},
        )
        rows = []
        for item in candidate_manifest():
            rows.append(
                row.model_copy(
                    update={
                        "candidate_id": item.candidate_id,
                        "candidate": item.display_name,
                        "provider_runtime": (
                            "OpenAI API" if item.provider == "openai" else "Ollama"
                        ),
                        "exact_model_tag": item.requested_model,
                        "evidence_origin": (
                            EvidenceOrigin.REUSED
                            if item.historical_evidence is not None
                            else EvidenceOrigin.NEW
                        ),
                    }
                )
            )
        matrix = build_matrix("synthetic-d2a", "0" * 40, rows)
        publish_matrix(matrix, candidate_manifest(), root)


def run_local_candidate(
    *,
    candidate: ModelCompatibilityCandidate,
    identity: LocalModelIdentity,
    diagnostic_id: str,
    output_root: Path,
    source_revision: str,
    provider_factory: Callable[[Settings], OpenAICompatibleProvider] = OpenAICompatibleProvider,
) -> tuple[CompatibilityRow, D2aRunArtifact]:
    _require_clean_tracked_worktree()
    _fixed_contract_preflight()
    if candidate.provider != "ollama" or identity.tag != candidate.requested_model:
        raise RuntimeError("D2A_MODEL_IDENTITY_MISMATCH")
    provider = provider_factory(_local_settings(identity.tag))
    synthetic = synthetic_run_artifact(candidate, identity)
    with tempfile.TemporaryDirectory(prefix="d2a-run-preflight-") as temp:
        publish_run(synthetic, Path(temp))
    budget = GenerationCallBudget(MAX_GENERATION_CALLS)
    counted = CountingProvider(provider, budget)
    cases = _cases_v1_2()
    try:
        warmup = _warmup(counted, cases[DIAGNOSTIC_CASE_IDS[0]])
        metadata = _run_metadata(
            candidate,
            diagnostic_id,
            identity,
            source_revision,
            provider,
            warmup,
        )
        attempts = [
            _run_attempt(
                counted,
                cases[case_id],
                run_index,
                contract_version=CONTRACT_VERSION,
                expected_decision_type=SemanticDecisionV3,
            )
            for case_id in DIAGNOSTIC_CASE_IDS
            for run_index in range(1, RUNS_PER_CASE + 1)
        ]
        if budget.calls != MAX_GENERATION_CALLS:
            raise RuntimeError("D2A_CALL_BUDGET_INCOMPLETE")
        transport = provider.structured_schema_metadata()
        transport["target_branch_required_fields"] = _target_branch_requirements(provider)
        artifact = D2aRunArtifact(
            metadata=metadata,
            provenance=_provenance(metadata),
            transport_schema=transport,
            attempts=attempts,
            summary=_complete_summary(attempts),
        )
        destination = publish_run(artifact, output_root)
    except Exception as error:
        invalid_root = output_root / "invalidated"
        invalid_root.mkdir(parents=True, exist_ok=True)
        invalid_path = invalid_root / f"{diagnostic_id}.json"
        if not invalid_path.exists():
            invalid_path.write_text(
                json.dumps(
                    {
                        "status": "INVALID",
                        "diagnostic_id": diagnostic_id,
                        "included_in_results": False,
                        "generation_calls": budget.calls,
                        "reason": type(error).__name__,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        raise
    paths = {name: str(destination / name) for name in REQUIRED_RUN_FILES}
    hashes = {name: _sha256(destination / name) for name in REQUIRED_RUN_FILES}
    row = _row_from_evidence(
        candidate=candidate,
        origin=EvidenceOrigin.NEW,
        diagnostic_id=diagnostic_id,
        metadata=metadata.model_dump(mode="json"),
        attempts=attempts,
        summary=artifact.summary,
        artifact_paths=paths,
        artifact_hashes=hashes,
    )
    return row, artifact


def unavailable_row(candidate: ModelCompatibilityCandidate) -> CompatibilityRow:
    return CompatibilityRow(
        candidate_id=candidate.candidate_id,
        candidate=candidate.display_name,
        provider_runtime="Ollama",
        exact_model_tag=candidate.requested_model,
        digest=None,
        quantization=None,
        runtime_version=None,
        evidence_origin=EvidenceOrigin.UNAVAILABLE,
        diagnostic_id=None,
        provider_success=None,
        structured_call_success=None,
        function_name_present=None,
        arguments_present=None,
        arguments_decoded=None,
        typed_semantic_decision_v3=None,
        typed_percentage=None,
        validation_failures=None,
        timeouts=None,
        dominant_failure_class="exact_local_model_not_installed_or_runtime_unavailable",
        en_typed=None,
        tr_typed=None,
        latency_ms=None,
        eligibility=Eligibility.UNAVAILABLE,
    )


def build_matrix(
    d2a_id: str, source_revision: str, rows: list[CompatibilityRow]
) -> CompatibilityMatrix:
    expected_ids = [candidate.candidate_id for candidate in candidate_manifest()]
    if [row.candidate_id for row in rows] != expected_ids:
        raise ValueError("D2A_MATRIX_CANDIDATE_ORDER_MISMATCH")
    eligible = [row.candidate for row in rows if row.eligibility is Eligibility.ELIGIBLE]
    review = [row.candidate for row in rows if row.eligibility is Eligibility.REVIEW]
    ineligible = [row.candidate for row in rows if row.eligibility is Eligibility.INELIGIBLE]
    unavailable = [row.candidate for row in rows if row.eligibility is Eligibility.UNAVAILABLE]
    invalid = any(row.eligibility is Eligibility.INVALID for row in rows)
    local_eligible = any(
        row.eligibility is Eligibility.ELIGIBLE and row.provider_runtime == "Ollama" for row in rows
    )
    if invalid:
        readiness = "D2A_EXPERIMENT_INVALID"
    elif review:
        readiness = "D2A_REVIEW_REQUIRED"
    elif not local_eligible:
        readiness = "NO_LOCAL_MODEL_ELIGIBLE"
    else:
        readiness = "READY_FOR_D2B"
    return CompatibilityMatrix(
        d2a_id=d2a_id,
        source_revision=source_revision,
        decision_schema_hash=EXPECTED_SCHEMA_HASH,
        function_schema_hash=EXPECTED_FUNCTION_SCHEMA_HASH,
        prompt_hash=EXPECTED_PROMPT_HASH,
        dataset_hash=EXPECTED_V1_2_HASH,
        targeted_subset_hash=targeted_subset_hash(live_cases_v1_2()),
        rows=rows,
        d2b_eligible_candidates=eligible,
        d2b_review_candidates=review,
        ineligible_candidates=ineligible,
        unavailable_candidates=unavailable,
        readiness=readiness,
    )


def _matrix_markdown(matrix: CompatibilityMatrix) -> str:
    lines = [
        "# D2a Semantic V3 Model/Runtime Compatibility Matrix",
        "",
        f"- Status: `{matrix.status}`",
        f"- Matrix: `{matrix.d2a_id}`",
        f"- Contract: `{matrix.decision_contract_version}`",
        f"- Dataset: `{matrix.dataset_version}`",
        f"- Eligibility rules: `{matrix.eligibility_rule_version}`",
        f"- Readiness: `{matrix.readiness}`",
        "",
        "| Candidate | Origin | Provider | Typed | Timeouts | Dominant failure | Eligibility |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in matrix.rows:
        typed = (
            "n/a"
            if row.typed_semantic_decision_v3 is None
            else f"{row.typed_semantic_decision_v3}/24"
        )
        timeout = "n/a" if row.timeouts is None else str(row.timeouts)
        lines.append(
            f"| {row.candidate} | {row.evidence_origin} | {row.provider_runtime} | "
            f"{typed} | {timeout} | {row.dominant_failure_class or 'none'} | "
            f"{row.eligibility} |"
        )
    lines.extend(
        [
            "",
            f"- D2B eligible: `{', '.join(matrix.d2b_eligible_candidates) or 'none'}`",
            f"- D2B review: `{', '.join(matrix.d2b_review_candidates) or 'none'}`",
            "- `direct_tool_v1` is not a D2b comparison arm; architecture is frozen.",
            "",
        ]
    )
    return "\n".join(lines)


def publish_matrix(
    matrix: CompatibilityMatrix,
    candidates: Iterable[ModelCompatibilityCandidate],
    output_root: Path,
) -> Path:
    manifest = {
        "status": "COMPLETE",
        "d2a_id": matrix.d2a_id,
        "source_revision": matrix.source_revision,
        "candidate_manifest": [item.model_dump(mode="json") for item in candidates],
        "protocol": {
            "contract_version": CONTRACT_VERSION,
            "decision_schema_hash": EXPECTED_SCHEMA_HASH,
            "function_schema_hash": EXPECTED_FUNCTION_SCHEMA_HASH,
            "prompt_hash": EXPECTED_PROMPT_HASH,
            "dataset_version": LIVE_CASE_SET_V1_2_VERSION,
            "dataset_hash": EXPECTED_V1_2_HASH,
            "targeted_subset_hash": matrix.targeted_subset_hash,
            "selected_case_ids": list(DIAGNOSTIC_CASE_IDS),
            "runs_per_case": RUNS_PER_CASE,
            "warmup_maximum": 1,
            "timeout_seconds": 30.0,
            "retry_count": 0,
            "eligibility_rule_version": ELIGIBILITY_RULE_VERSION,
        },
    }
    files = {
        "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        "compatibility_matrix.json": matrix.model_dump_json(indent=2) + "\n",
        "compatibility_matrix.md": _matrix_markdown(matrix),
    }
    destination = output_root / matrix.d2a_id
    _atomic_publish(destination, files)
    if not artifact_set_complete(destination, REQUIRED_MATRIX_FILES):
        raise RuntimeError("D2A_MATRIX_ARTIFACT_INCOMPLETE")
    return destination


def run_d2a(
    *,
    d2a_id: str,
    historical_root: Path,
    diagnostic_root: Path,
    matrix_root: Path,
    timestamp: str | None = None,
) -> CompatibilityMatrix:
    _require_clean_tracked_worktree()
    _fixed_contract_preflight()
    static_artifact_preflight()
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest = candidate_manifest()
    rows = [
        import_historical_evidence(manifest[0], historical_root),
        import_historical_evidence(manifest[1], historical_root),
    ]
    identities = {
        candidate.candidate_id: discover_local_model(candidate.requested_model)
        for candidate in manifest[2:]
    }
    run_timestamp = timestamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for candidate in manifest[2:]:
        identity = identities[candidate.candidate_id]
        if identity is None:
            rows.append(unavailable_row(candidate))
            continue
        diagnostic_id = f"d2a_{candidate.candidate_id}_{run_timestamp}"
        row, _ = run_local_candidate(
            candidate=candidate,
            identity=identity,
            diagnostic_id=diagnostic_id,
            output_root=diagnostic_root,
            source_revision=source_revision,
        )
        rows.append(row)
    matrix = build_matrix(d2a_id, source_revision, rows)
    publish_matrix(matrix, manifest, matrix_root)
    return matrix


def run_single_local_candidate(
    *,
    candidate_id: str,
    diagnostic_id: str,
    diagnostic_root: Path,
) -> tuple[CompatibilityRow, D2aRunArtifact]:
    """Run one explicitly selected local candidate without constructing a matrix."""

    _require_clean_tracked_worktree()
    _fixed_contract_preflight()
    static_artifact_preflight()
    candidates = {item.candidate_id: item for item in candidate_manifest()[2:]}
    candidate = candidates.get(candidate_id)
    if candidate is None:
        raise ValueError("D2A_NEW_LOCAL_CANDIDATE_REQUIRED")
    identity = discover_local_model(candidate.requested_model)
    if identity is None:
        raise RuntimeError("D2A_LOCAL_MODEL_UNAVAILABLE")
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return run_local_candidate(
        candidate=candidate,
        identity=identity,
        diagnostic_id=diagnostic_id,
        output_root=diagnostic_root,
        source_revision=source_revision,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument(
        "--historical-root",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    run = subparsers.add_parser("run")
    run.add_argument("--d2a-id", required=True)
    run.add_argument(
        "--historical-root",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    run.add_argument(
        "--diagnostic-root",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    run.add_argument("--matrix-root", type=Path, default=Path("artifacts/live-eval/model-matrix"))
    single = subparsers.add_parser("run-candidate")
    single.add_argument(
        "--candidate-id",
        choices=("qwen2_5_7b_instruct", "qwen3_5_9b"),
        required=True,
    )
    single.add_argument("--diagnostic-id", required=True)
    single.add_argument(
        "--diagnostic-root",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    _fixed_contract_preflight()
    static_artifact_preflight()
    manifest = candidate_manifest()
    if args.command == "preflight":
        for candidate in manifest[:2]:
            import_historical_evidence(candidate, args.historical_root)
        v1_1, v1_2 = validate_subset_equivalence()
        print(f"targeted_subset_hash_v1_1={v1_1}")
        print(f"targeted_subset_hash_v1_2={v1_2}")
        print("historical_controls=validated")
        return 0
    if args.command == "run-candidate":
        row, artifact = run_single_local_candidate(
            candidate_id=args.candidate_id,
            diagnostic_id=args.diagnostic_id,
            diagnostic_root=args.diagnostic_root,
        )
        print(f"diagnostic_id={artifact.metadata.diagnostic_id}")
        print(f"warmup_status={artifact.metadata.warmup.status}")
        print(f"typed_success={row.typed_semantic_decision_v3}/24")
        print(f"eligibility={row.eligibility}")
        return 0
    matrix = run_d2a(
        d2a_id=args.d2a_id,
        historical_root=args.historical_root,
        diagnostic_root=args.diagnostic_root,
        matrix_root=args.matrix_root,
    )
    print(f"d2a_id={matrix.d2a_id}")
    print(f"readiness={matrix.readiness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
