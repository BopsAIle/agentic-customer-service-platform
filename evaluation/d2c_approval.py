"""Create and validate immutable D2c review approvals without executing D2c."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from evaluation.d2c_oracle import (
    CONTRACT_SCHEMA_HASH,
    D2C_DATASET_DECISION_ID,
    D2C_ORACLE_SCHEMA_VERSION,
    D2C_SCORING_VERSION,
    FUNCTION_SCHEMA_HASH,
    PROMPT_HASH,
    LiveEvalV2Decision,
    canonical_live_eval_v2_decision,
    oracle_spec_hash,
)
from evaluation.d2c_spec import (
    D2C_APPROVAL_GATE_VERSION,
    D2C_SPEC_ARTIFACT_SHA256,
    D2C_SPEC_VERSION,
)
from evaluation.live_eval_v2 import (
    D2C_SCHEDULE_VERSION,
    LIVE_EVAL_V2_VERSION,
    d2c_schedule_hash,
    live_eval_v2_hash,
)
from evaluation.provenance import prompt_hash_for_contract, schema_hash_for_contract

D2C_APPROVAL_RECORD_SCHEMA_VERSION = "d2c_review_approval_record_v1"
D2C_DATASET_DECISION_SHA256 = "e72412c1d8afc47b62627fcf089b827b5012883ec9cfb36402ddba7a29228def"
D2A_DECISION_ID = "model_compatibility_d2a_v1"
D2A_DECISION_SHA256 = "79a04127a53c3cfa692441f8adeee2a0eb1999983b39e160bfa580d5dad01dee"
CONTRACT_VERSION = "semantic_decision_v3"
MODEL = "gpt-5.6-luna"
PROVIDER = "official OpenAI API"

SPEC_ARTIFACT_PATH = Path("evaluation/decisions/d2c_experiment_spec_v1.json")
DATASET_DECISION_PATH = Path("evaluation/decisions/live_eval_v2_decision.json")
D2A_DECISION_PATH = Path("evaluation/decisions/model_compatibility_d2a_v1.json")


class D2cEligibleRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    provider: Literal["official OpenAI API"] = "official OpenAI API"
    runtime: Literal["provider_managed"] = "provider_managed"
    d2a_eligibility: Literal["D2A_ELIGIBLE"] = "D2A_ELIGIBLE"
    structured_output_mode: Literal["function_calling"] = "function_calling"
    reasoning_effort: Literal["none"] = "none"
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    timeout_seconds: float = Field(default=30.0, ge=30.0, le=30.0)
    retry_count: Literal[0] = 0


class D2cReviewApproval(BaseModel):
    """Explicit review authority bound to every frozen D2c execution identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_schema_version: Literal["d2c_review_approval_record_v1"] = (
        "d2c_review_approval_record_v1"
    )
    status: Literal["APPROVED"]
    reviewed_confirmation: Literal[True]
    reviewer_identity: str = Field(min_length=3, max_length=200)
    approved_at: AwareDatetime
    approval_gate_version: Literal["d2c_review_approval_gate_v1"]
    approval_record_id: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )
    experiment_id: str = Field(pattern=r"^d2c_[a-z0-9_]+_\d{8}T\d{6}Z$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    spec_version: Literal["d2c_production_robustness_v1"]
    spec_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_decision_id: Literal["live_eval_v2_decision_v1"]
    dataset_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version: Literal["live_eval_v2"]
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_schema_version: Literal["d2c_oracle_v1"]
    scoring_version: Literal["d2c_scoring_v1"]
    oracle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schedule_version: Literal["d2c_case_major_repetition_v1"]
    schedule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_version: Literal["semantic_decision_v3"]
    contract_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    function_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligibility_decision_id: Literal["model_compatibility_d2a_v1"]
    eligibility_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_model_runtimes: tuple[D2cEligibleRuntime, ...]

    @field_validator("reviewer_identity")
    @classmethod
    def validate_reviewer_identity(cls, value: str) -> str:
        if value.strip() != value or not value.strip():
            raise ValueError("reviewer identity must be explicit and normalized")
        return value

    @field_validator("approved_at")
    @classmethod
    def validate_approval_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("approval timestamp must use UTC")
        return value

    @field_validator("eligible_model_runtimes")
    @classmethod
    def validate_eligible_model_runtimes(
        cls, value: tuple[D2cEligibleRuntime, ...]
    ) -> tuple[D2cEligibleRuntime, ...]:
        identities = [(runtime.model, runtime.provider) for runtime in value]
        if not value or len(identities) != len(set(identities)):
            raise ValueError("eligible model/runtime binding must be non-empty and unique")
        return value


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"D2C_FROZEN_ARTIFACT_MISSING:{path.as_posix()}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_identity_hash() -> str:
    """Hash the fixed semantic contract and transport/prompt identities as one binding."""

    payload = {
        "contract_version": CONTRACT_VERSION,
        "contract_schema_hash": CONTRACT_SCHEMA_HASH,
        "function_schema_hash": FUNCTION_SCHEMA_HASH,
        "prompt_hash": PROMPT_HASH,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_frozen_d2c_identities() -> LiveEvalV2Decision:
    """Fail closed if any source artifact or derived D2c identity has drifted."""

    if _sha256(SPEC_ARTIFACT_PATH) != D2C_SPEC_ARTIFACT_SHA256:
        raise RuntimeError("D2C_SPEC_ARTIFACT_HASH_MISMATCH")
    if _sha256(DATASET_DECISION_PATH) != D2C_DATASET_DECISION_SHA256:
        raise RuntimeError("D2C_DATASET_DECISION_HASH_MISMATCH")
    if _sha256(D2A_DECISION_PATH) != D2A_DECISION_SHA256:
        raise RuntimeError("D2C_ELIGIBILITY_DECISION_HASH_MISMATCH")

    decision = LiveEvalV2Decision.model_validate_json(
        DATASET_DECISION_PATH.read_text(encoding="utf-8")
    )
    if decision != canonical_live_eval_v2_decision():
        raise RuntimeError("D2C_DATASET_DECISION_CONTENT_MISMATCH")
    if decision.execution_authorized:
        raise RuntimeError("D2C_DATASET_DECISION_MUST_REMAIN_UNAPPROVED")
    if live_eval_v2_hash() != decision.dataset["sha256"]:
        raise RuntimeError("D2C_DATASET_HASH_MISMATCH")
    if oracle_spec_hash() != decision.oracle["sha256"]:
        raise RuntimeError("D2C_ORACLE_HASH_MISMATCH")
    if d2c_schedule_hash() != decision.schedule["sha256"]:
        raise RuntimeError("D2C_SCHEDULE_HASH_MISMATCH")
    if schema_hash_for_contract(CONTRACT_VERSION) != CONTRACT_SCHEMA_HASH:
        raise RuntimeError("D2C_CONTRACT_SCHEMA_HASH_MISMATCH")
    if prompt_hash_for_contract(CONTRACT_VERSION) != PROMPT_HASH:
        raise RuntimeError("D2C_PROMPT_HASH_MISMATCH")
    return decision


def build_review_approval(
    *,
    approval_record_id: str,
    reviewer_identity: str,
    approved_at: datetime,
    experiment_id: str,
    source_revision: str,
) -> D2cReviewApproval:
    """Build a reviewed record from verified frozen identities; never execute D2c."""

    decision = validate_frozen_d2c_identities()
    return D2cReviewApproval(
        status="APPROVED",
        reviewed_confirmation=True,
        reviewer_identity=reviewer_identity,
        approved_at=approved_at,
        approval_gate_version=D2C_APPROVAL_GATE_VERSION,
        approval_record_id=approval_record_id,
        experiment_id=experiment_id,
        source_revision=source_revision,
        spec_version=D2C_SPEC_VERSION,
        spec_artifact_sha256=D2C_SPEC_ARTIFACT_SHA256,
        dataset_decision_id=D2C_DATASET_DECISION_ID,
        dataset_decision_sha256=D2C_DATASET_DECISION_SHA256,
        dataset_version=LIVE_EVAL_V2_VERSION,
        dataset_hash=str(decision.dataset["sha256"]),
        oracle_schema_version=D2C_ORACLE_SCHEMA_VERSION,
        scoring_version=D2C_SCORING_VERSION,
        oracle_hash=str(decision.oracle["sha256"]),
        schedule_version=D2C_SCHEDULE_VERSION,
        schedule_hash=str(decision.schedule["sha256"]),
        contract_version=CONTRACT_VERSION,
        contract_identity_hash=contract_identity_hash(),
        contract_schema_hash=CONTRACT_SCHEMA_HASH,
        function_schema_hash=FUNCTION_SCHEMA_HASH,
        prompt_hash=PROMPT_HASH,
        eligibility_decision_id=D2A_DECISION_ID,
        eligibility_decision_sha256=D2A_DECISION_SHA256,
        eligible_model_runtimes=(D2cEligibleRuntime(),),
    )


def assert_review_approval_valid(
    approval: D2cReviewApproval | None,
    *,
    experiment_id: str,
    source_revision: str,
) -> None:
    """Validate explicit approval against current frozen inputs and requested execution."""

    if approval is None:
        raise RuntimeError("D2C_REVIEW_APPROVAL_REQUIRED")
    expected = build_review_approval(
        approval_record_id=approval.approval_record_id,
        reviewer_identity=approval.reviewer_identity,
        approved_at=approval.approved_at,
        experiment_id=experiment_id,
        source_revision=source_revision,
    )
    if approval != expected:
        raise RuntimeError("D2C_REVIEW_APPROVAL_MISMATCH")


def canonical_approval_bytes(approval: D2cReviewApproval) -> bytes:
    payload = approval.model_dump(mode="json")
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def approval_sha256(approval: D2cReviewApproval) -> str:
    return hashlib.sha256(canonical_approval_bytes(approval)).hexdigest()


def write_review_approval(approval: D2cReviewApproval, destination: Path) -> str:
    """Persist canonically and atomically while refusing every overwrite."""

    if destination.name != f"{approval.approval_record_id}.json":
        raise ValueError("approval filename must match approval_record_id")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_approval_bytes(approval)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.link(temporary_path, destination)
    except FileExistsError as exc:
        raise FileExistsError("approval record is immutable and already exists") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    load_review_approval(destination, expected_sha256=digest)
    return digest


def load_review_approval(path: Path, *, expected_sha256: str) -> D2cReviewApproval:
    """Load only a regular, canonical record matching an external SHA-256."""

    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("expected approval SHA-256 must be canonical lowercase hex")
    if path.is_symlink() or not path.is_file():
        raise ValueError("approval record must be a regular file")
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ValueError("approval record SHA-256 mismatch")
    approval = D2cReviewApproval.model_validate_json(content)
    if content != canonical_approval_bytes(approval):
        raise ValueError("approval record is not in canonical immutable format")
    return approval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="persist an explicit D2c review approval")
    create.add_argument("--approval-record-id", required=True)
    create.add_argument("--reviewer-identity", required=True)
    create.add_argument("--approved-at", required=True, help="explicit UTC ISO-8601 timestamp")
    create.add_argument("--experiment-id", required=True)
    create.add_argument("--source-revision", required=True)
    create.add_argument("--confirm-spec-sha256", required=True)
    create.add_argument("--confirm-decision-sha256", required=True)
    create.add_argument("--confirm-reviewed", action="store_true")
    create.add_argument("--output", required=True, type=Path)

    validate = subparsers.add_parser("validate", help="validate an existing D2c approval")
    validate.add_argument("--approval", required=True, type=Path)
    validate.add_argument("--expected-sha256", required=True)
    validate.add_argument("--experiment-id", required=True)
    validate.add_argument("--source-revision", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "create":
        if not args.confirm_reviewed:
            raise SystemExit("explicit --confirm-reviewed input is required")
        if not hmac.compare_digest(args.confirm_spec_sha256, D2C_SPEC_ARTIFACT_SHA256):
            raise SystemExit("confirmed D2c spec SHA-256 does not match")
        if not hmac.compare_digest(
            args.confirm_decision_sha256,
            D2C_DATASET_DECISION_SHA256,
        ):
            raise SystemExit("confirmed live_eval_v2 decision SHA-256 does not match")
        approval = build_review_approval(
            approval_record_id=args.approval_record_id,
            reviewer_identity=args.reviewer_identity,
            approved_at=datetime.fromisoformat(args.approved_at.replace("Z", "+00:00")),
            experiment_id=args.experiment_id,
            source_revision=args.source_revision,
        )
        digest = write_review_approval(approval, args.output)
        print(f"approval_path={args.output}")
        print(f"approval_sha256={digest}")
        print("execution_started=false")
        return 0

    approval = load_review_approval(args.approval, expected_sha256=args.expected_sha256)
    assert_review_approval_valid(
        approval,
        experiment_id=args.experiment_id,
        source_revision=args.source_revision,
    )
    print("approval_valid=true")
    print("execution_started=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
