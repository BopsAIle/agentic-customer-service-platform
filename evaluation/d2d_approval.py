"""Create, validate, and consume immutable D2d approval records."""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from evaluation.d2d.artifacts import canonical_json
from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    D2D_ARTIFACT_SCHEMA_VERSION,
    D2D_CONTRACT_SHA256,
    D2D_CONTRACT_VERSION,
    D2D_FAULT_MATRIX_SHA256,
    D2D_FAULT_MATRIX_VERSION,
    D2D_SCHEDULE_SHA256,
    D2D_SCHEDULE_VERSION,
    canonical_d2d_contract,
    validate_contract_identity,
)

D2D_APPROVAL_GATE_VERSION = "d2d_release_gate_approval_v1"
D2D_APPROVAL_RECORD_SCHEMA_VERSION = "d2d_release_gate_approval_record_v1"
D2D_ENVIRONMENT_FREEZE_SCHEMA_VERSION = "d2d_release_gate_environment_freeze_v1"
D2D_D2C_EXPERIMENT_ID = "d2c_m6_29_semantic_v3_20260822T011436Z"
D2D_D2C_SUMMARY_SHA256 = "6169745010cd67f578ff0fc7b67ce7f3c8703dfdb95e47ac14cf9ea691a281b3"
D2D_DRY_RUN_ID = "d2d_dryrun_m6_32_20260822T023921Z_77838"
D2D_DRY_RUN_RECORDED_SOURCE = "4079c6c56bf5d9e3e321c097bdbb8b27e9193202"
D2D_DRY_RUN_SUMMARY_SHA256 = "80f6f03a9a3a840ec9c7c4a3ad3370115b39f3c77af1e69c5ec2293c42a1a8c8"
D2D_DRY_RUN_ATTEMPTS_SHA256 = "8e387d478e7ccf368b0b9648e48b059451c9846ed404a23aba05a6dd09211bd8"
D2D_DRY_RUN_CLASSIFICATION = "D2D_DRY_RUN_PASS"
D2D_DRY_RUN_EVIDENCE_TYPE = "NON_GATING_DEVELOPMENT_EVIDENCE"
D2D_LIFECYCLE_SCHEMA_VERSION = "d2d_release_gate_approval_lifecycle_v1"

D2dApprovalState = Literal["CREATED", "APPROVED", "CONSUMED", "RUNNING", "PASSED", "FAILED"]
_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "CONSUMED": frozenset({"RUNNING"}),
    "RUNNING": frozenset({"PASSED", "FAILED"}),
}


class D2dEnvironmentFreeze(BaseModel):
    """Privacy-safe environment identity for one future D2d execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_schema_version: str = D2D_ENVIRONMENT_FREEZE_SCHEMA_VERSION
    status: Literal["FROZEN"] = "FROZEN"
    freeze_record_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    frozen_at: AwareDatetime
    experiment_id: str = Field(pattern=r"^d2d_m6_34_release_gate_\d{8}T\d{6}Z$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    contract_version: str = D2D_CONTRACT_VERSION
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schedule_version: str = D2D_SCHEDULE_VERSION
    schedule_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fault_matrix_version: str = D2D_FAULT_MATRIX_VERSION
    fault_matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_schema: str = D2D_ARTIFACT_SCHEMA_VERSION
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compose_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compose_files: tuple[str, ...]
    compose_project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    required_services: tuple[str, ...]
    image_identities: dict[str, str]
    toolchain: dict[str, str]
    alembic_head: str = D2D_ALEMBIC_HEAD
    provider_identity: Literal["NOT_APPLICABLE"] = "NOT_APPLICABLE"
    deterministic_provider: Literal["deterministic_integration"] = "deterministic_integration"
    same_action_concurrency: Literal[16] = 16
    same_action_rounds: Literal[3] = 3
    independent_action_concurrency: Literal[2] = 2
    independent_action_rounds: Literal[3] = 3
    automatic_retry_count: Literal[0] = 0
    automatic_rerun_count: Literal[0] = 0

    @field_validator("frozen_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("environment freeze timestamp must use UTC")
        return value


class D2dProspectiveApproval(BaseModel):
    """Explicit authority for exactly one future D2d run; never starts execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_schema_version: str = D2D_APPROVAL_RECORD_SCHEMA_VERSION
    approval_gate_version: str = D2D_APPROVAL_GATE_VERSION
    status: Literal["APPROVED"] = "APPROVED"
    reviewer_identity: str = Field(min_length=3, max_length=200)
    approved_at: AwareDatetime
    approval_record_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    experiment_id: str = Field(pattern=r"^d2d_m6_34_release_gate_\d{8}T\d{6}Z$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    contract_version: str = D2D_CONTRACT_VERSION
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schedule_version: str = D2D_SCHEDULE_VERSION
    schedule_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fault_matrix_version: str = D2D_FAULT_MATRIX_VERSION
    fault_matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_schema: str = D2D_ARTIFACT_SCHEMA_VERSION
    alembic_head: str = D2D_ALEMBIC_HEAD
    environment_freeze_record_id: str
    environment_freeze_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compose_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compose_project: str
    image_identities: dict[str, str]
    required_services: tuple[str, ...]
    same_action_concurrency: Literal[16] = 16
    same_action_rounds: Literal[3] = 3
    independent_action_concurrency: Literal[2] = 2
    independent_action_rounds: Literal[3] = 3
    automatic_retry_count: Literal[0] = 0
    automatic_rerun_count: Literal[0] = 0
    provider: Literal["NOT_APPLICABLE"] = "NOT_APPLICABLE"
    model: Literal["NOT_APPLICABLE"] = "NOT_APPLICABLE"
    d2c_prerequisite_experiment_id: str = D2D_D2C_EXPERIMENT_ID
    d2c_prerequisite_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    d2c_prerequisite_closure: Literal["CLOSED_FOR_CURRENT_RELEASE_CANDIDATE"] = (
        "CLOSED_FOR_CURRENT_RELEASE_CANDIDATE"
    )
    m6_32_dry_run_id: str = D2D_DRY_RUN_ID
    m6_32_dry_run_recorded_source: str = Field(pattern=r"^[0-9a-f]{40}$")
    m6_32_dry_run_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    m6_32_dry_run_attempts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    m6_32_dry_run_classification: str = D2D_DRY_RUN_CLASSIFICATION
    m6_32_evidence_type: str = D2D_DRY_RUN_EVIDENCE_TYPE
    m6_32_source_differs_from_approval_source: Literal[True] = True
    execution_started: Literal[False] = False
    consumed: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("approval timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def validate_fixed_values(self) -> D2dProspectiveApproval:
        if self.d2c_prerequisite_summary_sha256 != D2D_D2C_SUMMARY_SHA256:
            raise ValueError("D2D_D2C_PREREQUISITE_MISMATCH")
        if self.m6_32_dry_run_recorded_source != D2D_DRY_RUN_RECORDED_SOURCE:
            raise ValueError("D2D_M6_32_RECORDED_SOURCE_MISMATCH")
        if self.m6_32_dry_run_summary_sha256 != D2D_DRY_RUN_SUMMARY_SHA256:
            raise ValueError("D2D_M6_32_SUMMARY_MISMATCH")
        if self.m6_32_dry_run_attempts_sha256 != D2D_DRY_RUN_ATTEMPTS_SHA256:
            raise ValueError("D2D_M6_32_ATTEMPTS_MISMATCH")
        return self


class D2dApprovalLifecycle(BaseModel):
    """Append-only execution state for one approval consumption.

    The original approval remains immutable.  Each lifecycle state is published as a separate
    immutable record, and the consumed marker is claimed with an atomic filesystem operation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    lifecycle_schema_version: str = D2D_LIFECYCLE_SCHEMA_VERSION
    state: D2dApprovalState
    approval_record_id: str
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_valid: Literal[True] = True
    execution_started: bool
    consumed: bool
    execution_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    consumed_at: AwareDatetime
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    contract_sha: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_sha: str = Field(pattern=r"^[0-9a-f]{64}$")
    updated_at: AwareDatetime

    @field_validator("consumed_at", "updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("lifecycle timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def validate_state_flags(self) -> D2dApprovalLifecycle:
        if self.state in {"CREATED", "APPROVED"} and (self.execution_started or self.consumed):
            raise ValueError("D2D_APPROVAL_UNCONSUMED_STATE_INVALID")
        if self.state in {"CONSUMED", "RUNNING", "PASSED", "FAILED"} and not (
            self.execution_started and self.consumed
        ):
            raise ValueError("D2D_APPROVAL_CONSUMED_STATE_INVALID")
        return self


def _canonical_model_bytes(model: BaseModel) -> bytes:
    return canonical_json(model.model_dump(mode="json"))


def model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(_canonical_model_bytes(model)).hexdigest()


def _write_immutable(model: BaseModel, destination: Path, expected_name: str) -> str:
    if destination.name != expected_name:
        raise ValueError("immutable record filename does not match record identity")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_model_bytes(model)
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
    except FileExistsError as error:
        raise FileExistsError("immutable D2d record already exists") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(content).hexdigest()


def write_environment_freeze(freeze: D2dEnvironmentFreeze, destination: Path) -> str:
    expected_name = f"{freeze.freeze_record_id}.environment-freeze.json"
    return _write_immutable(freeze, destination, expected_name)


def write_approval(approval: D2dProspectiveApproval, destination: Path) -> str:
    return _write_immutable(approval, destination, f"{approval.approval_record_id}.json")


def write_lifecycle_state(state: D2dApprovalLifecycle, destination: Path) -> str:
    """Publish one immutable lifecycle state without overwriting an earlier state."""

    expected_name = f"{state.approval_record_id}.{state.execution_id}.{state.state.lower()}.json"
    return _write_immutable(state, destination, expected_name)


def load_lifecycle_state(path: Path, *, expected_sha256: str) -> D2dApprovalLifecycle:
    content = path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
        raise ValueError("D2D_LIFECYCLE_SHA256_MISMATCH")
    state = D2dApprovalLifecycle.model_validate_json(content)
    if content != _canonical_model_bytes(state):
        raise ValueError("D2D_LIFECYCLE_NONCANONICAL")
    return state


def transition_lifecycle(
    current: D2dApprovalLifecycle,
    next_state: Literal["RUNNING", "PASSED", "FAILED"],
    *,
    updated_at: datetime,
) -> D2dApprovalLifecycle:
    allowed = _LIFECYCLE_TRANSITIONS.get(current.state, frozenset())
    if next_state not in allowed:
        raise ValueError(f"D2D_LIFECYCLE_TRANSITION_INVALID:{current.state}->{next_state}")
    return current.model_copy(update={"state": next_state, "updated_at": updated_at})


def load_environment_freeze(path: Path, *, expected_sha256: str) -> D2dEnvironmentFreeze:
    content = path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
        raise ValueError("D2D_ENVIRONMENT_FREEZE_SHA256_MISMATCH")
    freeze = D2dEnvironmentFreeze.model_validate_json(content)
    if content != _canonical_model_bytes(freeze):
        raise ValueError("D2D_ENVIRONMENT_FREEZE_NONCANONICAL")
    return freeze


def load_approval(path: Path, *, expected_sha256: str) -> D2dProspectiveApproval:
    content = path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
        raise ValueError("D2D_APPROVAL_SHA256_MISMATCH")
    approval = D2dProspectiveApproval.model_validate_json(content)
    if content != _canonical_model_bytes(approval):
        raise ValueError("D2D_APPROVAL_NONCANONICAL")
    return approval


def validate_approval(
    approval: D2dProspectiveApproval,
    freeze: D2dEnvironmentFreeze,
    *,
    expected_source: str,
) -> None:
    """Validate every approval/freeze binding without starting operational execution."""

    validate_contract_identity(canonical_d2d_contract())
    if approval.execution_started or approval.consumed:
        raise ValueError("D2D_APPROVAL_ALREADY_CONSUMED")
    if approval.source_revision != expected_source or freeze.source_revision != expected_source:
        raise ValueError("D2D_SOURCE_BINDING_INVALID")
    if approval.experiment_id != freeze.experiment_id:
        raise ValueError("D2D_EXPERIMENT_BINDING_INVALID")
    for candidate in (approval, freeze):
        if candidate.contract_sha256 != D2D_CONTRACT_SHA256:
            raise ValueError("D2D_CONTRACT_BINDING_INVALID")
        if candidate.schedule_sha256 != D2D_SCHEDULE_SHA256:
            raise ValueError("D2D_SCHEDULE_BINDING_INVALID")
        if candidate.fault_matrix_sha256 != D2D_FAULT_MATRIX_SHA256:
            raise ValueError("D2D_FAULT_MATRIX_BINDING_INVALID")
        if candidate.artifact_schema != D2D_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("D2D_ARTIFACT_SCHEMA_BINDING_INVALID")
        if candidate.alembic_head != D2D_ALEMBIC_HEAD:
            raise ValueError("D2D_ALEMBIC_HEAD_BINDING_INVALID")
    if approval.environment_freeze_record_id != freeze.freeze_record_id:
        raise ValueError("D2D_ENVIRONMENT_FREEZE_RECORD_MISMATCH")
    if approval.environment_freeze_sha256 != model_sha256(freeze):
        raise ValueError("D2D_ENVIRONMENT_FREEZE_BINDING_INVALID")
    if approval.configuration_sha256 != freeze.configuration_sha256:
        raise ValueError("D2D_CONFIGURATION_BINDING_INVALID")
    if approval.compose_config_sha256 != freeze.compose_config_sha256:
        raise ValueError("D2D_COMPOSE_BINDING_INVALID")
    if approval.image_identities != freeze.image_identities:
        raise ValueError("D2D_IMAGE_BINDING_INVALID")
    if approval.required_services != freeze.required_services:
        raise ValueError("D2D_SERVICE_BINDING_INVALID")
    if approval.same_action_concurrency != 16 or approval.same_action_rounds != 3:
        raise ValueError("D2D_SAME_ACTION_BINDING_INVALID")
    if approval.independent_action_concurrency != 2 or approval.independent_action_rounds != 3:
        raise ValueError("D2D_INDEPENDENT_ACTION_BINDING_INVALID")
    if approval.automatic_retry_count != 0 or approval.automatic_rerun_count != 0:
        raise ValueError("D2D_RETRY_POLICY_INVALID")
    if approval.provider != "NOT_APPLICABLE" or approval.model != "NOT_APPLICABLE":
        raise ValueError("D2D_PROVIDER_BINDING_INVALID")


def consume_approval(
    approval: D2dProspectiveApproval,
    freeze: D2dEnvironmentFreeze,
    *,
    approval_sha256: str,
    expected_source: str,
    execution_id: str,
    consumed_at: datetime,
    lifecycle_root: Path,
) -> tuple[D2dApprovalLifecycle, str]:
    """Atomically claim an approved record after all pre-execution checks pass.

    The claim file is deliberately named by approval record ID.  A second execution cannot
    create the same marker, even if it uses a different execution ID.
    """

    validate_approval(approval, freeze, expected_source=expected_source)
    canonical_approval_sha = hashlib.sha256(_canonical_model_bytes(approval)).hexdigest()
    if not hmac.compare_digest(approval_sha256, canonical_approval_sha):
        raise ValueError("D2D_APPROVAL_SHA256_MISMATCH")
    if consumed_at.utcoffset() != timedelta(0):
        raise ValueError("D2D_CONSUMPTION_TIMESTAMP_NOT_UTC")
    environment_sha = model_sha256(freeze)
    lifecycle = D2dApprovalLifecycle(
        state="CONSUMED",
        approval_record_id=approval.approval_record_id,
        approval_sha256=approval_sha256,
        execution_started=True,
        consumed=True,
        execution_id=execution_id,
        consumed_at=consumed_at,
        source_sha=approval.source_revision,
        contract_sha=approval.contract_sha256,
        environment_sha=environment_sha,
        updated_at=consumed_at,
    )
    claim_path = lifecycle_root / f"{approval.approval_record_id}.consumed.json"
    return lifecycle, _write_immutable(lifecycle, claim_path, claim_path.name)


def safe_configuration_sha256(configuration: Mapping[str, object]) -> str:
    """Hash only the caller-provided privacy-safe configuration projection."""

    return hashlib.sha256(canonical_json(dict(configuration))).hexdigest()
