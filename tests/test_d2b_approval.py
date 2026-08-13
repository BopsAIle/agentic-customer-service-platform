from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.d2b_approval import (
    approval_sha256,
    build_review_approval,
    canonical_approval_bytes,
    load_review_approval,
    main,
    write_review_approval,
)
from evaluation.d2b_spec import (
    D2B_SPEC_ARTIFACT_SHA256,
    D2bReviewApproval,
    assert_execution_approved,
    canonical_d2b_spec,
)

EXPERIMENT_ID = "d2b_semantic_v3_20260813T220000Z"
SOURCE_REVISION = "a" * 40


def _approval() -> D2bReviewApproval:
    return build_review_approval(
        approval_record_id="review-record",
        reviewer_identity="reviewer@example.test",
        approved_at=datetime(2026, 8, 13, 22, tzinfo=UTC),
        experiment_id=EXPERIMENT_ID,
        source_revision=SOURCE_REVISION,
    )


def test_approval_binds_all_frozen_execution_identities() -> None:
    spec = canonical_d2b_spec()
    approval = _approval()
    assert approval.reviewer_identity == "reviewer@example.test"
    assert approval.approved_at == datetime(2026, 8, 13, 22, tzinfo=UTC)
    assert approval.spec_artifact_sha256 == D2B_SPEC_ARTIFACT_SHA256
    assert approval.experiment_id == EXPERIMENT_ID
    assert approval.source_revision == SOURCE_REVISION
    assert approval.dataset_hash == spec.dataset_hash
    assert approval.contract_schema_hash == spec.contract_schema_hash
    assert approval.function_schema_hash == spec.function_schema_hash
    assert [candidate.model for candidate in approval.eligible_candidates] == ["gpt-5.6-luna"]
    assert [candidate.provider for candidate in approval.eligible_candidates] == [
        "official OpenAI API"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spec_artifact_sha256", "0" * 64),
        ("experiment_id", "d2b_semantic_v3_20260813T220001Z"),
        ("source_revision", "b" * 40),
        ("decision_record_revision", "b" * 40),
        ("dataset_hash", "0" * 64),
        ("contract_schema_hash", "0" * 64),
        ("function_schema_hash", "0" * 64),
        ("prompt_hash", "0" * 64),
        ("eligible_candidates", ()),
    ],
)
def test_approval_gate_rejects_every_identity_mismatch(field: str, value: object) -> None:
    approval = _approval().model_copy(update={field: value})
    with pytest.raises(RuntimeError, match="D2B_REVIEW_APPROVAL_MISMATCH"):
        assert_execution_approved(
            canonical_d2b_spec(),
            approval,
            experiment_id=EXPERIMENT_ID,
            source_revision=SOURCE_REVISION,
        )


def test_approval_requires_explicit_utc_reviewer_timestamp() -> None:
    payload = _approval().model_dump(mode="json")
    payload["reviewer_identity"] = "  "
    with pytest.raises(ValidationError):
        D2bReviewApproval.model_validate(payload)
    payload = _approval().model_dump(mode="json")
    payload["approved_at"] = "2026-08-14T01:00:00+03:00"
    with pytest.raises(ValidationError):
        D2bReviewApproval.model_validate(payload)


def test_approval_persistence_is_canonical_hash_bound_and_non_overwriting(
    tmp_path: Path,
) -> None:
    approval = _approval()
    destination = tmp_path / "review-record.json"
    digest = write_review_approval(approval, destination)
    assert digest == approval_sha256(approval)
    assert destination.read_bytes() == canonical_approval_bytes(approval)
    assert load_review_approval(destination, expected_sha256=digest) == approval
    with pytest.raises(FileExistsError, match="immutable"):
        write_review_approval(approval, destination)


def test_approval_loader_rejects_tampering_and_noncanonical_json(tmp_path: Path) -> None:
    approval = _approval()
    destination = tmp_path / "review-record.json"
    destination.write_bytes(canonical_approval_bytes(approval) + b" ")
    digest = approval_sha256(approval)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_review_approval(destination, expected_sha256=digest)
    changed_digest = __import__("hashlib").sha256(destination.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="canonical immutable format"):
        load_review_approval(destination, expected_sha256=changed_digest)


def test_approval_loader_rejects_extra_fields_even_with_matching_hash(tmp_path: Path) -> None:
    payload = _approval().model_dump(mode="json")
    payload["unreviewed"] = True
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    destination = tmp_path / "review-record.json"
    destination.write_bytes(content)
    digest = __import__("hashlib").sha256(content).hexdigest()
    with pytest.raises(ValidationError):
        load_review_approval(destination, expected_sha256=digest)


def test_create_cli_requires_real_explicit_confirmation_and_does_not_execute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "review-record.json"
    common = [
        "create",
        "--approval-record-id",
        "review-record",
        "--reviewer-identity",
        "reviewer@example.test",
        "--approved-at",
        "2026-08-13T22:00:00Z",
        "--experiment-id",
        EXPERIMENT_ID,
        "--source-revision",
        SOURCE_REVISION,
        "--confirm-spec-sha256",
        D2B_SPEC_ARTIFACT_SHA256,
        "--output",
        str(destination),
    ]
    with pytest.raises(SystemExit, match="explicit --confirm-reviewed"):
        main(common)
    assert not destination.exists()

    assert main([*common, "--confirm-reviewed"]) == 0
    output = capsys.readouterr().out
    assert "execution_started=false" in output
    assert "approval_sha256=" in output
    assert destination.exists()


def test_approval_module_has_no_model_or_live_artifact_path() -> None:
    source = Path("evaluation/d2b_approval.py").read_text(encoding="utf-8")
    assert "OpenAI" not in source
    assert "Ollama" not in source
    assert "artifacts/live-eval" not in source
    assert ".decide(" not in source
