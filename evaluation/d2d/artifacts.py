"""Bounded D2d artifacts, privacy checks, and atomic publication."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluation.d2d_spec import (
    D2D_ARTIFACT_SCHEMA_VERSION,
    D2D_CONTRACT_SHA256,
    D2D_CONTRACT_VERSION,
    D2D_FAULT_MATRIX_SHA256,
    D2D_FAULT_MATRIX_VERSION,
    D2D_SCHEDULE_SHA256,
    D2D_SCHEDULE_VERSION,
    canonical_d2d_contract,
)


class D2dAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(gt=0)
    phase: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    execution_mode: Literal["dry_run", "prospective_release"] = "dry_run"
    execution_path: Literal["compose_http", "compose_dependency", "deterministic_harness"]
    status: Literal["PASS", "FAIL"]
    failure_category: str | None = None
    duration_ms: float = Field(ge=0)
    readiness_state: str | None = None
    migration_status: str | None = None
    confirmation_state: str | None = None
    mutation_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    unauthorized_mutation_count: int = Field(ge=0)
    confirmation_bypass_count: int = Field(ge=0)
    recovery_status: str | None = None
    observability_status: str | None = None
    privacy_status: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class D2dEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha: str
    contract_version: str = D2D_CONTRACT_VERSION
    contract_sha: str = D2D_CONTRACT_SHA256
    schedule_version: str = D2D_SCHEDULE_VERSION
    schedule_sha: str = D2D_SCHEDULE_SHA256
    fault_matrix_version: str = D2D_FAULT_MATRIX_VERSION
    fault_matrix_sha: str = D2D_FAULT_MATRIX_SHA256
    artifact_schema: str = D2D_ARTIFACT_SCHEMA_VERSION
    execution_mode: Literal["dry_run", "prospective_release"] = "dry_run"
    approval_status: Literal["not_approved", "approved"] = "not_approved"
    safe_configuration_hash: str
    compose_project: str
    required_services: tuple[str, ...]
    image_identities: dict[str, str] = Field(default_factory=dict)
    alembic_head_expected: str
    alembic_head_actual: str
    provider_identity: str = "deterministic_integration"
    automatic_retry_count: int = 0
    automatic_rerun_count: int = 0


class D2dSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["COMPLETE", "INVALID"]
    execution_mode: Literal["dry_run", "prospective_release"] = "dry_run"
    approval_status: Literal["not_approved", "approved"] = "not_approved"
    classification: Literal[
        "D2D_DRY_RUN_PASS",
        "D2D_DRY_RUN_FAIL",
        "D2D_DRY_RUN_INVALID",
        "D2D_RELEASE_GATE_PASS",
        "D2D_PRODUCT_SAFETY_FAILURE",
        "D2D_CONCURRENCY_IDEMPOTENCY_FAILURE",
        "D2D_PERSISTENCE_RECOVERY_FAILURE",
        "D2D_DEPLOYMENT_READINESS_FAILURE",
        "D2D_OBSERVABILITY_PRIVACY_FAILURE",
        "D2D_EXECUTION_INVALID_OR_INCOMPLETE",
    ]
    dimensions: dict[str, Literal["PASS", "FAIL", "NOT_RUN"]]
    scenario_count: int
    phase_count: int
    fault_count: int
    retries: int = 0
    automatic_reruns: int = 0
    same_action_concurrency: dict[str, object]
    independent_action_concurrency: dict[str, object]
    privacy_violations: int = 0
    release_gate: Literal["NON_APPROVED_DRY_RUN", "PROSPECTIVE_RELEASE_GATE"] = (
        "NON_APPROVED_DRY_RUN"
    )


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_configuration_hash(values: dict[str, object]) -> str:
    allowed = {str(key): values[key] for key in sorted(values)}
    return sha256_bytes(canonical_json(allowed))


_FORBIDDEN_KEYS = {
    "authorization",
    "api_key",
    "credential",
    "password",
    "prompt",
    "raw_user_text",
    "raw_provider_response",
    "refund_reason",
    "chain_of_thought",
    "reasoning",
    "memory_content",
    "rag_content",
}


def privacy_violations(value: object, path: str = "$", *, _allowlist: bool = False) -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_KEYS or any(
                part in normalized for part in ("secret", "token")
            ):
                violations.append(f"{path}.{key}")
            violations.extend(privacy_violations(nested, f"{path}.{key}"))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            violations.extend(privacy_violations(nested, f"{path}[{index}]"))
    return violations


class D2dArtifactPublisher:
    """Publish a validated five-file dry-run bundle without overwriting prior runs."""

    FILES = ("manifest.json", "environment.json", "attempts.json", "summary.json", "summary.md")

    def __init__(self, root: Path) -> None:
        self.root = root

    def publish(
        self,
        run_id: str,
        environment: D2dEnvironment,
        attempts: list[D2dAttempt],
        summary: D2dSummary,
        summary_markdown: str,
    ) -> tuple[Path, dict[str, str]]:
        if environment.execution_mode != "dry_run" or environment.approval_status != "not_approved":
            raise ValueError("D2D_DRY_RUN_IDENTITY_INVALID")
        if summary.execution_mode != "dry_run" or summary.approval_status != "not_approved":
            raise ValueError("D2D_DRY_RUN_IDENTITY_INVALID")
        if any(item.execution_mode != "dry_run" for item in attempts):
            raise ValueError("D2D_DRY_RUN_ATTEMPT_MODE_INVALID")
        target = self.root / run_id
        if target.exists():
            raise FileExistsError(f"D2D dry-run already exists: {run_id}")
        if len(attempts) != 18:
            raise ValueError("D2D dry-run must contain exactly 18 scenario records")
        contract = canonical_d2d_contract()
        if tuple(item.ordinal for item in attempts) != tuple(range(1, 19)):
            raise ValueError("D2D_SCENARIO_ORDINALS_INVALID")
        if tuple(item.scenario_id for item in attempts) != tuple(
            scenario.scenario_id for scenario in contract.scenarios
        ):
            raise ValueError("D2D_SCENARIO_ORDER_INVALID")
        for value in (
            environment.model_dump(mode="json"),
            [item.model_dump(mode="json") for item in attempts],
            summary.model_dump(mode="json"),
            summary_markdown,
        ):
            violations = privacy_violations(value)
            if violations:
                raise ValueError(f"D2D_PRIVACY_VIOLATION:{violations[0]}")
        payloads = {
            "environment.json": canonical_json(environment.model_dump(mode="json")),
            "attempts.json": canonical_json([item.model_dump(mode="json") for item in attempts]),
            "summary.json": canonical_json(summary.model_dump(mode="json")),
            "summary.md": summary_markdown.encode(),
        }
        hashes = {name: sha256_bytes(data) for name, data in payloads.items()}
        manifest = {
            "artifact_type": "d2d_dry_run_manifest",
            "artifact_schema": D2D_ARTIFACT_SCHEMA_VERSION,
            "run_id": run_id,
            "execution_mode": "dry_run",
            "approval_status": "not_approved",
            "status": summary.status,
            "files": hashes,
        }
        payloads["manifest.json"] = canonical_json(manifest)
        all_hashes = {name: sha256_bytes(data) for name, data in payloads.items()}
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{run_id}.", dir=self.root) as temp:
            staging = Path(temp)
            for name, data in payloads.items():
                (staging / name).write_bytes(data)
            for name in self.FILES:
                if not (staging / name).is_file():
                    raise ValueError(f"D2D_ARTIFACT_MISSING:{name}")
            os.replace(staging, target)
        return target, all_hashes


class D2dReleaseArtifactPublisher:
    """Publish one approved prospective release-gate bundle without overwriting."""

    FILES = D2dArtifactPublisher.FILES

    def __init__(self, root: Path) -> None:
        self.root = root

    def publish(
        self,
        run_id: str,
        environment: D2dEnvironment,
        attempts: list[D2dAttempt],
        summary: D2dSummary,
        summary_markdown: str,
        *,
        approval_sha256: str,
        execution_id: str,
    ) -> tuple[Path, dict[str, str]]:
        if environment.execution_mode != "prospective_release":
            raise ValueError("D2D_RELEASE_ENVIRONMENT_MODE_INVALID")
        if environment.approval_status != "approved":
            raise ValueError("D2D_RELEASE_APPROVAL_STATUS_INVALID")
        if summary.execution_mode != "prospective_release":
            raise ValueError("D2D_RELEASE_SUMMARY_MODE_INVALID")
        if summary.approval_status != "approved":
            raise ValueError("D2D_RELEASE_SUMMARY_APPROVAL_INVALID")
        if summary.release_gate != "PROSPECTIVE_RELEASE_GATE":
            raise ValueError("D2D_RELEASE_GATE_MARKER_INVALID")
        if summary.status != "COMPLETE":
            raise ValueError("D2D_RELEASE_PARTIAL_RUN_INVALID")
        if summary.classification != "D2D_RELEASE_GATE_PASS":
            raise ValueError("D2D_RELEASE_CLASSIFICATION_INVALID")
        if len(attempts) != 18:
            raise ValueError("D2D_RELEASE_SCENARIO_COUNT_INVALID")
        if any(item.execution_mode != "prospective_release" for item in attempts):
            raise ValueError("D2D_RELEASE_ATTEMPT_MODE_INVALID")
        if privacy_violations(
            {
                "environment": environment.model_dump(mode="json"),
                "attempts": [item.model_dump(mode="json") for item in attempts],
                "summary": summary.model_dump(mode="json"),
                "summary_markdown": summary_markdown,
            }
        ):
            raise ValueError("D2D_PRIVACY_VIOLATION")
        target = self.root / run_id
        if target.exists():
            raise FileExistsError(f"D2D release gate already exists: {run_id}")
        payloads = {
            "environment.json": canonical_json(environment.model_dump(mode="json")),
            "attempts.json": canonical_json([item.model_dump(mode="json") for item in attempts]),
            "summary.json": canonical_json(summary.model_dump(mode="json")),
            "summary.md": summary_markdown.encode(),
        }
        hashes = {name: sha256_bytes(data) for name, data in payloads.items()}
        manifest = {
            "artifact_type": "d2d_release_gate_manifest",
            "artifact_schema": D2D_ARTIFACT_SCHEMA_VERSION,
            "run_id": run_id,
            "execution_id": execution_id,
            "execution_mode": "prospective_release",
            "approval_status": "approved",
            "approval_consumed": True,
            "approval_sha256": approval_sha256,
            "status": summary.status,
            "files": hashes,
        }
        payloads["manifest.json"] = canonical_json(manifest)
        all_hashes = {name: sha256_bytes(data) for name, data in payloads.items()}
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{run_id}.", dir=self.root) as temp:
            staging = Path(temp)
            for name, data in payloads.items():
                (staging / name).write_bytes(data)
            os.replace(staging, target)
        return target, all_hashes


def validate_published_bundle(path: Path) -> dict[str, str]:
    if not path.is_dir():
        raise ValueError("D2D_ARTIFACT_DIRECTORY_MISSING")
    for name in D2dArtifactPublisher.FILES:
        if not (path / name).is_file():
            raise ValueError(f"D2D_ARTIFACT_MISSING:{name}")
    manifest = json.loads((path / "manifest.json").read_text())
    mode = manifest.get("execution_mode")
    if mode == "dry_run":
        if manifest.get("approval_status") != "not_approved":
            raise ValueError("D2D_DRY_RUN_IDENTITY_INVALID")
    elif mode == "prospective_release":
        if (
            manifest.get("approval_status") != "approved"
            or manifest.get("approval_consumed") is not True
            or not isinstance(manifest.get("approval_sha256"), str)
        ):
            raise ValueError("D2D_RELEASE_IDENTITY_INVALID")
    else:
        raise ValueError("D2D_EXECUTION_MODE_INVALID")
    hashes = manifest.get("files")
    if not isinstance(hashes, dict):
        raise ValueError("D2D_MANIFEST_HASHES_MISSING")
    actual: dict[str, str] = {}
    for name in D2dArtifactPublisher.FILES:
        actual[name] = sha256_bytes((path / name).read_bytes())
        if name != "manifest.json" and hashes.get(name) != actual[name]:
            raise ValueError(f"D2D_ARTIFACT_HASH_MISMATCH:{name}")
    summary = json.loads((path / "summary.json").read_text())
    environment = json.loads((path / "environment.json").read_text())
    attempts = json.loads((path / "attempts.json").read_text())
    if not isinstance(attempts, list):
        raise ValueError("D2D_ATTEMPTS_INVALID")
    expected_approval_status = "approved" if mode == "prospective_release" else "not_approved"
    expected_mode = mode
    if (
        environment.get("execution_mode") != expected_mode
        or environment.get("approval_status") != expected_approval_status
        or summary.get("execution_mode") != expected_mode
        or summary.get("approval_status") != expected_approval_status
        or any(
            item.get("execution_mode") != expected_mode
            for item in attempts
            if isinstance(item, dict)
        )
    ):
        raise ValueError("D2D_ARTIFACT_MODE_RELATIONSHIP_INVALID")
    if mode == "dry_run" and summary.get("release_gate") != "NON_APPROVED_DRY_RUN":
        raise ValueError("D2D_DRY_RUN_RELEASE_GATE_MARKER_MISSING")
    if mode == "prospective_release":
        if summary.get("release_gate") != "PROSPECTIVE_RELEASE_GATE":
            raise ValueError("D2D_RELEASE_GATE_MARKER_MISSING")
        if summary.get("classification") != "D2D_RELEASE_GATE_PASS":
            raise ValueError("D2D_RELEASE_CLASSIFICATION_INVALID")
    if privacy_violations(summary) or privacy_violations(attempts):
        raise ValueError("D2D_PRIVACY_VIOLATION")
    return actual
