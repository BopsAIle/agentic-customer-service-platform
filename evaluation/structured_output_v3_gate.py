"""Canonical targeted semantic_decision_v3 compatibility gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import SemanticDecisionV3
from app.core.config import Settings
from evaluation.architecture_ab import _model_metadata
from evaluation.live_cases import (
    LIVE_CASE_SET_V1_1_VERSION,
    LiveEvalCase,
    live_cases_v1_1,
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
    _counts,
    _run_attempt,
)
from evaluation.structured_output_openai_control import (
    OPENAI_BASE_URL,
    CountingProvider,
    GenerationCallBudget,
    list_openai_model_ids,
    select_luna_model,
)

GATE_SCHEMA_VERSION = "structured_output_v3_compatibility_gate_v1"
COMPARISON_SCHEMA_VERSION = "structured_output_v3_compatibility_comparison_v1"
CONTRACT_VERSION = "semantic_decision_v3"
QWEN_MODEL = "qwen3.5:4b"
QWEN_DIGEST = "2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
QWEN_BASE_URL = "http://127.0.0.1:11434/v1"
LUNA_MODEL = "gpt-5.6-luna"
MEASURED_ATTEMPTS = len(DIAGNOSTIC_CASE_IDS) * RUNS_PER_CASE
MAX_GENERATION_CALLS = 1 + MEASURED_ATTEMPTS
REQUIRED_ARM_FILES = frozenset({"attempts.json", "summary.json", "summary.md"})
REQUIRED_COMPARISON_FILES = frozenset({"comparison.json", "comparison.md"})

Arm = Literal["qwen", "luna"]


class GateRunStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"


class StructuredOutputGateMetadata(BaseModel):
    """Single metadata contract shared by all V3 gate writers and renderers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostic_id: str = Field(min_length=1)
    diagnostic_schema_version: str = GATE_SCHEMA_VERSION
    decision_contract_version: str
    decision_schema_hash: str = Field(min_length=64, max_length=64)
    function_schema_hash: str = Field(min_length=64, max_length=64)
    prompt_hash: str = Field(min_length=64, max_length=64)
    dataset_version: str
    case_set_hash: str = Field(min_length=64, max_length=64)
    base_revision: str = Field(min_length=40, max_length=40)
    provider: Literal["ollama", "openai"]
    model: str
    model_digest: str | None = None
    quantization: str | None = None
    runtime: str
    runtime_version: str | None = None
    structured_output_mode: Literal["function_calling"]
    reasoning_effort: Literal["none"]
    temperature: float
    timeout_seconds: float
    retry_count: int = Field(ge=0)
    runs_per_case: int = Field(gt=0)
    measured_attempts: int = Field(gt=0)
    warmup_count: int = Field(ge=0, le=1)
    selected_case_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_frozen_methodology(self) -> StructuredOutputGateMetadata:
        if self.decision_contract_version != CONTRACT_VERSION:
            raise ValueError("unexpected decision contract")
        if self.decision_schema_hash != schema_hash_for_contract(CONTRACT_VERSION):
            raise ValueError("decision schema hash mismatch")
        if self.prompt_hash != prompt_hash_for_contract(CONTRACT_VERSION):
            raise ValueError("prompt hash mismatch")
        metadata = case_set_metadata(live_cases_v1_1(), version=LIVE_CASE_SET_V1_1_VERSION)
        if self.dataset_version != LIVE_CASE_SET_V1_1_VERSION:
            raise ValueError("dataset version mismatch")
        if self.case_set_hash != metadata["sha256"]:
            raise ValueError("case-set hash mismatch")
        if self.structured_output_mode != "function_calling":
            raise ValueError("structured-output mode mismatch")
        if self.reasoning_effort != "none":
            raise ValueError("reasoning effort mismatch")
        if self.temperature != 0.0 or self.timeout_seconds != 30.0:
            raise ValueError("request configuration mismatch")
        if self.retry_count != 0:
            raise ValueError("retries are forbidden")
        if self.runs_per_case != RUNS_PER_CASE:
            raise ValueError("runs-per-case mismatch")
        if self.measured_attempts != MEASURED_ATTEMPTS:
            raise ValueError("measured-attempt count mismatch")
        if self.warmup_count != 1:
            raise ValueError("warmup count mismatch")
        if self.selected_case_ids != DIAGNOSTIC_CASE_IDS:
            raise ValueError("targeted case-set mismatch")
        return self


class GateRunArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[GateRunStatus.COMPLETE] = GateRunStatus.COMPLETE
    metadata: StructuredOutputGateMetadata
    provenance: dict[str, Any]
    transport_schema: dict[str, Any]
    attempts: list[DiagnosticAttempt]
    summary: dict[str, Any]


class GateComparisonMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: str
    comparison_schema_version: str = COMPARISON_SCHEMA_VERSION
    base_revision: str = Field(min_length=40, max_length=40)
    decision_contract_version: str
    decision_schema_hash: str = Field(min_length=64, max_length=64)
    prompt_hash: str = Field(min_length=64, max_length=64)
    dataset_version: str
    case_set_hash: str = Field(min_length=64, max_length=64)
    qwen_diagnostic_id: str
    luna_diagnostic_id: str


class GateComparisonArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[GateRunStatus.COMPLETE] = GateRunStatus.COMPLETE
    metadata: GateComparisonMetadata
    qwen_summary: dict[str, Any]
    luna_summary: dict[str, Any]
    historical_invalidated_runs: list[dict[str, Any]]


class InvalidatedGateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[GateRunStatus.INVALID] = GateRunStatus.INVALID
    diagnostic_id: str
    included_in_results: Literal[False] = False
    generation_calls: int = Field(ge=0)
    reason: str


HISTORICAL_INVALIDATED_RUNS = (
    InvalidatedGateRun(
        diagnostic_id="structured_output_v3_qwen3_5_4b_20260813T191200Z",
        generation_calls=25,
        reason="artifact_write_failure",
    ),
)


def _cases() -> dict[str, LiveEvalCase]:
    cases = {case.id: case for case in live_cases_v1_1()}
    missing = [case_id for case_id in DIAGNOSTIC_CASE_IDS if case_id not in cases]
    if missing:
        raise RuntimeError(f"live_eval_v1_1 cases missing: {', '.join(missing)}")
    return cases


def _settings(*, arm: Arm, api_key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        llm_provider="openai_compatible",
        llm_model=QWEN_MODEL if arm == "qwen" else LUNA_MODEL,
        llm_base_url=QWEN_BASE_URL if arm == "qwen" else OPENAI_BASE_URL,
        llm_api_key=None if arm == "qwen" else api_key,
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


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _require_clean_tracked_worktree() -> None:
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise RuntimeError("GATE_SOURCE_WORKTREE_NOT_CLEAN")


def _target_branch_requirements(provider: OpenAICompatibleProvider) -> dict[str, list[str]]:
    schema = provider._transport_schema
    if not schema:
        raise RuntimeError("transport schema unavailable")
    target = schema["properties"]["target"]
    union = next(item for item in target["anyOf"] if "oneOf" in item)
    return {
        str(branch["properties"]["type"]["const"]): list(branch.get("required", []))
        for branch in union["oneOf"]
    }


def _gate_metadata(
    *,
    arm: Arm,
    diagnostic_id: str,
    provider: OpenAICompatibleProvider,
    base_revision: str,
    model_metadata: dict[str, Any] | None = None,
) -> StructuredOutputGateMetadata:
    case_metadata = case_set_metadata(live_cases_v1_1(), version=LIVE_CASE_SET_V1_1_VERSION)
    schema_metadata = provider.structured_schema_metadata()
    supplied = model_metadata or {}
    return StructuredOutputGateMetadata(
        diagnostic_id=diagnostic_id,
        decision_contract_version=CONTRACT_VERSION,
        decision_schema_hash=schema_hash_for_contract(CONTRACT_VERSION),
        function_schema_hash=str(schema_metadata["transport_schema_hash"]),
        prompt_hash=prompt_hash_for_contract(CONTRACT_VERSION),
        dataset_version=LIVE_CASE_SET_V1_1_VERSION,
        case_set_hash=str(case_metadata["sha256"]),
        base_revision=base_revision,
        provider="ollama" if arm == "qwen" else "openai",
        model=QWEN_MODEL if arm == "qwen" else LUNA_MODEL,
        model_digest=supplied.get("model_digest"),
        quantization=supplied.get("quantization"),
        runtime="Ollama" if arm == "qwen" else "OpenAI API",
        runtime_version=supplied.get("runtime_version"),
        structured_output_mode="function_calling",
        reasoning_effort="none",
        temperature=0.0,
        timeout_seconds=30.0,
        retry_count=0,
        runs_per_case=RUNS_PER_CASE,
        measured_attempts=MEASURED_ATTEMPTS,
        warmup_count=1,
        selected_case_ids=DIAGNOSTIC_CASE_IDS,
    )


def gate_configuration(*, arm: Arm, model_id: str) -> dict[str, Any]:
    """Return the stable request methodology without credentials."""

    del model_id
    provider = OpenAICompatibleProvider(_settings(arm=arm, api_key="not-persisted"))
    metadata = _gate_metadata(
        arm=arm,
        diagnostic_id="configuration-preflight",
        provider=provider,
        base_revision="0" * 40,
    )
    return metadata.model_dump(mode="json")


def _warmup(provider: CountingProvider, case: LiveEvalCase) -> None:
    provider.decide(
        messages=[{"role": "user", "content": case.rendered_input()}],
        customer_id=case.customer_id,
    )


def _failure_taxonomy(attempts: list[DiagnosticAttempt]) -> dict[str, Any]:
    errors = Counter[str]()
    target_failures = 0
    missing_explicit_identifier = 0
    reason_length_failures = 0
    root_model_type_failures = 0
    transport_failures = 0
    decode_failures = 0
    target_failure_cases = Counter[str]()
    for attempt in attempts:
        diagnostic = attempt.validation_diagnostic
        if diagnostic is None:
            continue
        if diagnostic.stage.value == "STRUCTURED_OUTPUT_TRANSPORT_FAILURE":
            transport_failures += 1
        if diagnostic.stage.value == "FUNCTION_ARGUMENT_DECODE_FAILURE":
            decode_failures += 1
        for error in diagnostic.errors:
            signature = f"{error.type}@{error.location}"
            errors[signature] += 1
            if error.location == "reason" and error.type == "string_too_long":
                reason_length_failures += 1
            if error.location == "<root>" and error.type == "model_type":
                root_model_type_failures += 1
            if error.location.startswith("target"):
                target_failures += 1
                target_failure_cases[attempt.case_id] += 1
                if (
                    attempt.target_variant == "explicit_order"
                    and "order_id" not in attempt.target_keys
                    and error.type in {"missing", "value_error"}
                ):
                    missing_explicit_identifier += 1
    return {
        "normalized_errors": dict(sorted(errors.items())),
        "target_failures": target_failures,
        "target_failures_by_case": dict(sorted(target_failure_cases.items())),
        "explicit_target_missing_identifier": missing_explicit_identifier,
        "reason_length_failures": reason_length_failures,
        "root_model_type_failures": root_model_type_failures,
        "transport_failures": transport_failures,
        "argument_decode_failures": decode_failures,
    }


def compatibility_classification(successes: int, attempts: int) -> str:
    if attempts <= 0:
        return "EXPERIMENT_INVALID"
    rate = successes / attempts
    if rate >= 23 / 24:
        return "HIGH_COMPATIBILITY"
    if rate >= 0.5:
        return "PARTIAL_COMPATIBILITY"
    return "LOW_COMPATIBILITY"


def _summary(attempts: list[DiagnosticAttempt]) -> dict[str, Any]:
    counts = _counts(attempts)
    return {
        **counts,
        "failure_taxonomy": _failure_taxonomy(attempts),
        "compatibility_classification": compatibility_classification(
            int(counts["typed_decision_success"]), len(attempts)
        ),
        "structured_call_present": sum(
            attempt.structured_call_present is True for attempt in attempts
        ),
        "function_name_present": sum(attempt.function_name_present is True for attempt in attempts),
        "arguments_present": sum(attempt.arguments_present is True for attempt in attempts),
        "arguments_decoded": sum(attempt.arguments_decoded is True for attempt in attempts),
        "typed_model_constructed": sum(attempt.typed_model_constructed for attempt in attempts),
    }


def _render_arm_markdown(artifact: GateRunArtifact) -> str:
    metadata = artifact.metadata
    summary = artifact.summary
    return "\n".join(
        [
            "# Semantic Decision V3 Compatibility Gate",
            "",
            f"- Status: `{artifact.status}`",
            f"- Diagnostic: `{metadata.diagnostic_id}`",
            f"- Contract: `{metadata.decision_contract_version}`",
            f"- Contract schema: `{metadata.decision_schema_hash}`",
            f"- Function schema: `{metadata.function_schema_hash}`",
            f"- Dataset: `{metadata.dataset_version}` / `{metadata.case_set_hash}`",
            f"- Source revision: `{metadata.base_revision}`",
            f"- Provider/model: `{metadata.provider}` / `{metadata.model}`",
            f"- Attempts: `{summary['attempts']}`",
            f"- Typed decisions: `{summary['typed_decision_success']}`",
            f"- Validation failures: `{summary['validation_failures']}`",
            "",
            "## Failure taxonomy",
            "",
            "```json",
            json.dumps(summary["failure_taxonomy"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Per-case results",
            "",
            "```json",
            json.dumps(summary["by_case"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )


def _render_comparison_markdown(artifact: GateComparisonArtifact) -> str:
    metadata = artifact.metadata
    return "\n".join(
        [
            "# Semantic Decision V3 Dual-Model Compatibility Comparison",
            "",
            f"- Status: `{artifact.status}`",
            f"- Comparison: `{metadata.comparison_id}`",
            f"- Contract: `{metadata.decision_contract_version}`",
            f"- Contract schema: `{metadata.decision_schema_hash}`",
            f"- Dataset: `{metadata.dataset_version}` / `{metadata.case_set_hash}`",
            f"- Source revision: `{metadata.base_revision}`",
            f"- Qwen diagnostic: `{metadata.qwen_diagnostic_id}`",
            f"- Luna diagnostic: `{metadata.luna_diagnostic_id}`",
            "",
            "| Model | Provider success | Typed decisions | Classification |",
            "|---|---:|---:|---|",
            (
                f"| Qwen | {artifact.qwen_summary['provider_success']}/24 | "
                f"{artifact.qwen_summary['typed_decision_success']}/24 | "
                f"{artifact.qwen_summary['compatibility_classification']} |"
            ),
            (
                f"| Luna | {artifact.luna_summary['provider_success']}/24 | "
                f"{artifact.luna_summary['typed_decision_success']}/24 | "
                f"{artifact.luna_summary['compatibility_classification']} |"
            ),
            "",
        ]
    )


def _atomic_publish(directory: Path, files: dict[str, str]) -> None:
    if directory.exists():
        raise FileExistsError(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=directory.parent))
    try:
        for name, content in files.items():
            path = temporary / name
            path.write_text(content, encoding="utf-8")
            path.read_text(encoding="utf-8")
        temporary.rename(directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _arm_files(artifact: GateRunArtifact) -> dict[str, str]:
    attempts_payload = {
        "status": artifact.status,
        "metadata": artifact.metadata.model_dump(mode="json"),
        "provenance": artifact.provenance,
        "transport_schema": artifact.transport_schema,
        "attempts": [attempt.model_dump(mode="json") for attempt in artifact.attempts],
    }
    summary_payload = {
        "status": artifact.status,
        "metadata": artifact.metadata.model_dump(mode="json"),
        "summary": artifact.summary,
    }
    return {
        "attempts.json": json.dumps(attempts_payload, indent=2, ensure_ascii=False) + "\n",
        "summary.json": json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        "summary.md": _render_arm_markdown(artifact),
    }


def _comparison_files(artifact: GateComparisonArtifact) -> dict[str, str]:
    return {
        "comparison.json": artifact.model_dump_json(indent=2) + "\n",
        "comparison.md": _render_comparison_markdown(artifact),
    }


def artifact_set_complete(directory: Path, required: Iterable[str]) -> bool:
    required_set = set(required)
    if not directory.is_dir() or not required_set.issubset(
        {path.name for path in directory.iterdir() if path.is_file()}
    ):
        return False
    for name in required_set:
        path = directory / name
        if path.stat().st_size == 0:
            return False
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") != GateRunStatus.COMPLETE:
                return False
    return True


def publish_arm_artifact(artifact: GateRunArtifact, output_root: Path) -> Path:
    destination = output_root / artifact.metadata.diagnostic_id
    _atomic_publish(destination, _arm_files(artifact))
    if not artifact_set_complete(destination, REQUIRED_ARM_FILES):
        raise RuntimeError("ARM_ARTIFACT_SET_INCOMPLETE")
    return destination


def publish_comparison_artifact(artifact: GateComparisonArtifact, output_root: Path) -> Path:
    destination = output_root / artifact.metadata.comparison_id
    _atomic_publish(destination, _comparison_files(artifact))
    if not artifact_set_complete(destination, REQUIRED_COMPARISON_FILES):
        raise RuntimeError("COMPARISON_ARTIFACT_SET_INCOMPLETE")
    return destination


def _synthetic_attempt(case_id: str, language: str, run_index: int) -> DiagnosticAttempt:
    return DiagnosticAttempt(
        case_id=case_id,
        language=language,
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


def _synthetic_artifact(metadata: StructuredOutputGateMetadata) -> GateRunArtifact:
    attempts = [
        _synthetic_attempt(case_id, _cases()[case_id].language, run_index)
        for case_id in DIAGNOSTIC_CASE_IDS
        for run_index in range(1, RUNS_PER_CASE + 1)
    ]
    return GateRunArtifact(
        metadata=metadata,
        provenance={"preflight": True},
        transport_schema={"transport_schema_hash": metadata.function_schema_hash},
        attempts=attempts,
        summary=_summary(attempts),
    )


def static_artifact_preflight(
    qwen_metadata: StructuredOutputGateMetadata,
    luna_metadata: StructuredOutputGateMetadata,
) -> None:
    with tempfile.TemporaryDirectory(prefix="semantic-v3-gate-preflight-") as temp_dir:
        root = Path(temp_dir)
        qwen = _synthetic_artifact(qwen_metadata)
        luna = _synthetic_artifact(luna_metadata)
        publish_arm_artifact(qwen, root)
        publish_arm_artifact(luna, root)
        comparison = build_comparison_artifact(
            comparison_id="synthetic-comparison",
            qwen=qwen,
            luna=luna,
        )
        publish_comparison_artifact(comparison, root)


def _provenance(metadata: StructuredOutputGateMetadata) -> dict[str, Any]:
    args = argparse.Namespace(
        model=metadata.model,
        base_url=QWEN_BASE_URL if metadata.provider == "ollama" else OPENAI_BASE_URL,
        structured_output_mode=metadata.structured_output_mode,
        reasoning_effort=metadata.reasoning_effort,
        temperature=metadata.temperature,
        timeout=metadata.timeout_seconds,
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
    if metadata.provider == "ollama":
        provenance["model"].update(
            {
                "model_digest": metadata.model_digest,
                "quantization": metadata.quantization,
            }
        )
    else:
        provenance["model"].update(
            {
                "provider": "openai",
                "model_name": metadata.model,
                "exact_model_identifier": metadata.model,
                "model_digest": None,
                "quantization": None,
                "inference_hardware": "provider_managed",
            }
        )
        provenance["runtime"].update(
            {
                "runtime_name": "OpenAI API",
                "runtime_version": None,
                "endpoint_classification": "official_openai_api",
                "transport": "openai_compatible_chat_completions",
            }
        )
    return provenance


def run_arm(
    *,
    arm: Arm,
    diagnostic_id: str,
    output_root: Path,
    api_key: str | None = None,
    discovered_model_id: str | None = None,
    model_metadata: dict[str, Any] | None = None,
    require_clean_source: bool = True,
    provider_factory: Callable[[Settings], OpenAICompatibleProvider] = OpenAICompatibleProvider,
    render_preflight: bool = True,
) -> GateRunArtifact:
    if require_clean_source:
        _require_clean_tracked_worktree()
    if arm == "luna" and discovered_model_id != LUNA_MODEL:
        raise RuntimeError("OPENAI_LUNA_NOT_AVAILABLE")
    if arm == "qwen" and (model_metadata or {}).get("model_digest") != QWEN_DIGEST:
        raise RuntimeError("QWEN_MODEL_DIGEST_MISMATCH")

    provider = provider_factory(_settings(arm=arm, api_key=api_key))
    metadata = _gate_metadata(
        arm=arm,
        diagnostic_id=diagnostic_id,
        provider=provider,
        base_revision=_git_revision(),
        model_metadata=model_metadata,
    )
    if render_preflight:
        other_arm: Arm = "luna" if arm == "qwen" else "qwen"
        other_provider = provider_factory(
            _settings(arm=other_arm, api_key="preflight-not-persisted")
        )
        other_metadata = _gate_metadata(
            arm=other_arm,
            diagnostic_id=f"{diagnostic_id}-other-preflight",
            provider=other_provider,
            base_revision=metadata.base_revision,
            model_metadata={"model_digest": QWEN_DIGEST, "quantization": "Q4_K_M"},
        )
        static_artifact_preflight(
            metadata if arm == "qwen" else other_metadata,
            other_metadata if arm == "qwen" else metadata,
        )

    budget = GenerationCallBudget(MAX_GENERATION_CALLS)
    counted = CountingProvider(provider, budget)
    cases = _cases()
    try:
        _warmup(counted, cases[DIAGNOSTIC_CASE_IDS[0]])
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
            raise RuntimeError("V3_GATE_CALL_BUDGET_INCOMPLETE")
        schema_metadata = provider.structured_schema_metadata()
        schema_metadata["target_branch_required_fields"] = _target_branch_requirements(provider)
        artifact = GateRunArtifact(
            metadata=metadata,
            provenance=_provenance(metadata),
            transport_schema=schema_metadata,
            attempts=attempts,
            summary=_summary(attempts),
        )
        publish_arm_artifact(artifact, output_root)
        return artifact
    except Exception as error:
        invalid = InvalidatedGateRun(
            diagnostic_id=diagnostic_id,
            generation_calls=budget.calls,
            reason=(
                "artifact_write_failure"
                if budget.calls == MAX_GENERATION_CALLS
                else type(error).__name__
            ),
        )
        invalid_root = output_root / "invalidated"
        invalid_root.mkdir(parents=True, exist_ok=True)
        invalid_path = invalid_root / f"{diagnostic_id}.json"
        if not invalid_path.exists():
            invalid_path.write_text(invalid.model_dump_json(indent=2) + "\n", encoding="utf-8")
        raise


def build_comparison_artifact(
    *, comparison_id: str, qwen: GateRunArtifact, luna: GateRunArtifact
) -> GateComparisonArtifact:
    qwen_metadata = qwen.metadata
    luna_metadata = luna.metadata
    shared = (
        "base_revision",
        "decision_contract_version",
        "decision_schema_hash",
        "prompt_hash",
        "dataset_version",
        "case_set_hash",
    )
    if any(getattr(qwen_metadata, key) != getattr(luna_metadata, key) for key in shared):
        raise ValueError("gate arm metadata mismatch")
    return GateComparisonArtifact(
        metadata=GateComparisonMetadata(
            comparison_id=comparison_id,
            base_revision=qwen_metadata.base_revision,
            decision_contract_version=qwen_metadata.decision_contract_version,
            decision_schema_hash=qwen_metadata.decision_schema_hash,
            prompt_hash=qwen_metadata.prompt_hash,
            dataset_version=qwen_metadata.dataset_version,
            case_set_hash=qwen_metadata.case_set_hash,
            qwen_diagnostic_id=qwen_metadata.diagnostic_id,
            luna_diagnostic_id=luna_metadata.diagnostic_id,
        ),
        qwen_summary=qwen.summary,
        luna_summary=luna.summary,
        historical_invalidated_runs=[
            item.model_dump(mode="json") for item in HISTORICAL_INVALIDATED_RUNS
        ],
    )


def publish_comparison(
    *,
    comparison_id: str,
    qwen: GateRunArtifact,
    luna: GateRunArtifact,
    output_root: Path,
) -> GateComparisonArtifact:
    artifact = build_comparison_artifact(comparison_id=comparison_id, qwen=qwen, luna=luna)
    publish_comparison_artifact(artifact, output_root)
    return artifact


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_hashes(directory: Path, required: Iterable[str]) -> dict[str, str]:
    if not artifact_set_complete(directory, required):
        raise RuntimeError("artifact set is incomplete")
    return {name: _sha256(directory / name) for name in sorted(required)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("qwen", "luna"), required=True)
    parser.add_argument("--diagnostic-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    api_key: str | None = None
    discovered: str | None = None
    model_metadata: dict[str, Any] | None = None
    if args.arm == "luna":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required")
        discovered = select_luna_model(list_openai_model_ids(api_key))
    else:
        model_metadata = _model_metadata(QWEN_BASE_URL, QWEN_MODEL)
    artifact = run_arm(
        arm=args.arm,
        diagnostic_id=args.diagnostic_id,
        output_root=args.output_root,
        api_key=api_key,
        discovered_model_id=discovered,
        model_metadata=model_metadata,
    )
    print(f"diagnostic_id={artifact.metadata.diagnostic_id}")
    print(f"typed_success={artifact.summary['typed_decision_success']}/{MEASURED_ATTEMPTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
