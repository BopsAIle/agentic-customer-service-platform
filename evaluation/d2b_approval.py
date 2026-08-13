"""Create and validate immutable, reviewed D2b approval records without executing D2b."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from evaluation.d2b_spec import (
    D2A_DECISION_ID,
    D2A_DECISION_REVISION,
    D2B_APPROVAL_GATE_VERSION,
    D2B_SPEC_ARTIFACT_SHA256,
    D2bReviewApproval,
    assert_execution_approved,
    canonical_d2b_spec,
)


def build_review_approval(
    *,
    approval_record_id: str,
    reviewer_identity: str,
    approved_at: datetime,
    experiment_id: str,
    source_revision: str,
) -> D2bReviewApproval:
    """Bind explicit review input to every frozen D2b execution identity."""

    spec = canonical_d2b_spec()
    return D2bReviewApproval(
        status="APPROVED",
        reviewer_identity=reviewer_identity,
        approved_at=approved_at,
        approval_gate_version=D2B_APPROVAL_GATE_VERSION,
        spec_version=spec.spec_version,
        spec_artifact_sha256=D2B_SPEC_ARTIFACT_SHA256,
        experiment_id=experiment_id,
        source_revision=source_revision,
        decision_record_id=D2A_DECISION_ID,
        decision_record_revision=D2A_DECISION_REVISION,
        dataset_version=spec.dataset_version,
        dataset_hash=spec.dataset_hash,
        contract_version=spec.contract_version,
        contract_schema_hash=spec.contract_schema_hash,
        function_schema_hash=spec.function_schema_hash,
        prompt_hash=spec.prompt_hash,
        eligible_candidates=spec.eligible_candidates,
        approval_record_id=approval_record_id,
    )


def canonical_approval_bytes(approval: D2bReviewApproval) -> bytes:
    """Return the one accepted timestamp-free serialization of an approval record."""

    payload = approval.model_dump(mode="json")
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def approval_sha256(approval: D2bReviewApproval) -> str:
    return hashlib.sha256(canonical_approval_bytes(approval)).hexdigest()


def write_review_approval(approval: D2bReviewApproval, destination: Path) -> str:
    """Persist canonically and atomically, refusing to replace an existing approval."""

    if destination.name != f"{approval.approval_record_id}.json":
        raise ValueError("approval filename must match approval_record_id")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_approval_bytes(approval)
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
    except FileExistsError as exc:
        raise FileExistsError("approval record is immutable and already exists") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    load_review_approval(destination, expected_sha256=digest)
    return digest


def load_review_approval(path: Path, *, expected_sha256: str) -> D2bReviewApproval:
    """Load a canonical approval only when its externally supplied digest matches."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("approval record must be a regular file")
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ValueError("approval record SHA-256 mismatch")
    approval = D2bReviewApproval.model_validate_json(content)
    if content != canonical_approval_bytes(approval):
        raise ValueError("approval record is not in canonical immutable format")
    return approval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="persist an explicit reviewed approval")
    create.add_argument("--approval-record-id", required=True)
    create.add_argument("--reviewer-identity", required=True)
    create.add_argument("--approved-at", required=True, help="explicit UTC ISO-8601 timestamp")
    create.add_argument("--experiment-id", required=True)
    create.add_argument("--source-revision", required=True)
    create.add_argument("--confirm-spec-sha256", required=True)
    create.add_argument("--confirm-reviewed", action="store_true")
    create.add_argument("--output", required=True, type=Path)

    validate = subparsers.add_parser("validate", help="validate an existing reviewed approval")
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
        if not hmac.compare_digest(args.confirm_spec_sha256, D2B_SPEC_ARTIFACT_SHA256):
            raise SystemExit("confirmed D2b spec SHA-256 does not match")
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
    assert_execution_approved(
        canonical_d2b_spec(),
        approval,
        experiment_id=args.experiment_id,
        source_revision=args.source_revision,
    )
    print("approval_valid=true")
    print("execution_started=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
