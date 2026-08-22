from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import evaluation.d2c_approval as approval_module
from evaluation.d2c_approval import (
    D2A_DECISION_ID,
    D2A_DECISION_SHA256,
    D2C_DATASET_DECISION_SHA256,
    D2cReviewApproval,
    approval_sha256,
    assert_review_approval_valid,
    build_review_approval,
    canonical_approval_bytes,
    contract_identity_hash,
    load_review_approval,
    main,
    validate_frozen_d2c_identities,
    write_review_approval,
)
from evaluation.d2c_oracle import (
    CONTRACT_SCHEMA_HASH,
    D2C_DATASET_DECISION_ID,
    FUNCTION_SCHEMA_HASH,
    PROMPT_HASH,
    oracle_spec_hash,
)
from evaluation.d2c_spec import D2C_SPEC_ARTIFACT_SHA256, D2C_SPEC_VERSION
from evaluation.live_eval_v2 import d2c_schedule_hash, live_eval_v2_hash

EXPERIMENT_ID = "d2c_production_robustness_v1_20260814T010203Z"
SOURCE_REVISION = "1" * 40
APPROVED_AT = datetime(2026, 8, 14, 1, 2, 3, tzinfo=UTC)


def _approval() -> D2cReviewApproval:
    return build_review_approval(
        approval_record_id="d2c-review-20260814T010203Z",
        reviewer_identity="reviewer@example.test",
        approved_at=APPROVED_AT,
        experiment_id=EXPERIMENT_ID,
        source_revision=SOURCE_REVISION,
    )


def test_d2c_approval_binds_every_frozen_execution_identity() -> None:
    approval = _approval()

    assert approval.reviewed_confirmation is True
    assert approval.reviewer_identity == "reviewer@example.test"
    assert approval.approved_at == APPROVED_AT
    assert approval.spec_version == D2C_SPEC_VERSION
    assert approval.spec_artifact_sha256 == D2C_SPEC_ARTIFACT_SHA256
    assert approval.dataset_decision_id == D2C_DATASET_DECISION_ID
    assert approval.dataset_decision_sha256 == D2C_DATASET_DECISION_SHA256
    assert approval.dataset_hash == live_eval_v2_hash()
    assert approval.oracle_hash == oracle_spec_hash()
    assert approval.schedule_hash == d2c_schedule_hash()
    assert approval.contract_version == "semantic_decision_v3"
    assert (
        approval.contract_identity_hash
        == contract_identity_hash()
        == ("c660e7e28fb1592b1ef4170551e814a9fe58a8b3e8518246a48093544cf9285f")
    )
    assert approval.contract_schema_hash == CONTRACT_SCHEMA_HASH
    assert approval.function_schema_hash == FUNCTION_SCHEMA_HASH
    assert approval.prompt_hash == PROMPT_HASH
    assert approval.eligibility_decision_id == D2A_DECISION_ID
    assert approval.eligibility_decision_sha256 == D2A_DECISION_SHA256
    assert [runtime.model for runtime in approval.eligible_model_runtimes] == ["gpt-5.6-luna"]
    assert [runtime.provider for runtime in approval.eligible_model_runtimes] == [
        "official OpenAI API"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_hash", "2" * 64),
        ("oracle_hash", "3" * 64),
        ("schedule_hash", "4" * 64),
        ("dataset_decision_sha256", "5" * 64),
        ("contract_identity_hash", "6" * 64),
        ("contract_schema_hash", "7" * 64),
        ("function_schema_hash", "8" * 64),
        ("prompt_hash", "9" * 64),
        ("eligible_model_runtimes", ()),
    ],
)
def test_d2c_approval_gate_rejects_every_frozen_identity_mismatch(
    field: str, value: object
) -> None:
    mismatched = _approval().model_copy(update={field: value})

    with pytest.raises(RuntimeError, match="D2C_REVIEW_APPROVAL_MISMATCH"):
        assert_review_approval_valid(
            mismatched,
            experiment_id=EXPERIMENT_ID,
            source_revision=SOURCE_REVISION,
        )


def test_d2c_approval_gate_rejects_mismatched_source_experiment_and_model() -> None:
    approval = _approval()
    wrong_runtime = approval.eligible_model_runtimes[0].model_copy(
        update={"model": "not-the-approved-model"}
    )

    with pytest.raises(RuntimeError, match="D2C_REVIEW_APPROVAL_MISMATCH"):
        assert_review_approval_valid(
            approval,
            experiment_id=EXPERIMENT_ID,
            source_revision="2" * 40,
        )
    with pytest.raises(RuntimeError, match="D2C_REVIEW_APPROVAL_MISMATCH"):
        assert_review_approval_valid(
            approval,
            experiment_id="d2c_other_20260814T010203Z",
            source_revision=SOURCE_REVISION,
        )
    with pytest.raises(RuntimeError, match="D2C_REVIEW_APPROVAL_MISMATCH"):
        assert_review_approval_valid(
            approval.model_copy(update={"eligible_model_runtimes": (wrong_runtime,)}),
            experiment_id=EXPERIMENT_ID,
            source_revision=SOURCE_REVISION,
        )


def test_d2c_approval_requires_valid_hashes_utc_reviewer_and_review_confirmation() -> None:
    payload = _approval().model_dump(mode="json")
    payload["oracle_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        D2cReviewApproval.model_validate(payload)

    payload = _approval().model_dump(mode="json")
    payload["reviewer_identity"] = " reviewer@example.test"
    with pytest.raises(ValidationError):
        D2cReviewApproval.model_validate(payload)

    payload = _approval().model_dump(mode="json")
    payload["approved_at"] = "2026-08-14T04:02:03+03:00"
    with pytest.raises(ValidationError):
        D2cReviewApproval.model_validate(payload)

    payload = _approval().model_dump(mode="json")
    payload["reviewed_confirmation"] = False
    with pytest.raises(ValidationError):
        D2cReviewApproval.model_validate(payload)


def test_d2c_approval_rejects_extra_fields() -> None:
    payload = _approval().model_dump(mode="json")
    payload["authorization_override"] = True

    with pytest.raises(ValidationError):
        D2cReviewApproval.model_validate(payload)


def test_d2c_approval_persistence_is_canonical_atomic_and_non_overwriting(
    tmp_path: Path,
) -> None:
    approval = _approval()
    destination = tmp_path / f"{approval.approval_record_id}.json"

    digest = write_review_approval(approval, destination)

    assert digest == approval_sha256(approval)
    assert destination.read_bytes() == canonical_approval_bytes(approval)
    assert load_review_approval(destination, expected_sha256=digest) == approval
    assert not list(tmp_path.glob(f".{destination.name}.*"))
    with pytest.raises(FileExistsError, match="immutable"):
        write_review_approval(approval, destination)


def test_d2c_approval_loader_rejects_tampering_noncanonical_json_and_invalid_digest(
    tmp_path: Path,
) -> None:
    approval = _approval()
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_approval_bytes(approval) + b" ")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="not in canonical"):
        load_review_approval(path, expected_sha256=digest)
    with pytest.raises(ValueError, match="canonical lowercase hex"):
        load_review_approval(path, expected_sha256="z" * 64)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_review_approval(path, expected_sha256="0" * 64)


def test_d2c_approval_loader_rejects_extra_fields_even_with_matching_hash(
    tmp_path: Path,
) -> None:
    payload = _approval().model_dump(mode="json")
    payload["extra"] = "forbidden"
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path = tmp_path / "approval.json"
    path.write_bytes(content)

    with pytest.raises(ValidationError):
        load_review_approval(path, expected_sha256=hashlib.sha256(content).hexdigest())


def test_d2c_frozen_artifact_integrity_is_checked_before_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drifted = tmp_path / "decision.json"
    drifted.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(approval_module, "DATASET_DECISION_PATH", drifted)

    with pytest.raises(RuntimeError, match="D2C_DATASET_DECISION_HASH_MISMATCH"):
        validate_frozen_d2c_identities()


def test_d2c_approval_cli_requires_review_and_hash_confirmations(
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
        "2026-08-14T01:02:03Z",
        "--experiment-id",
        EXPERIMENT_ID,
        "--source-revision",
        SOURCE_REVISION,
        "--confirm-spec-sha256",
        D2C_SPEC_ARTIFACT_SHA256,
        "--confirm-decision-sha256",
        D2C_DATASET_DECISION_SHA256,
        "--output",
        str(destination),
    ]

    with pytest.raises(SystemExit, match="confirm-reviewed"):
        main(common)
    assert not destination.exists()

    assert main([*common, "--confirm-reviewed"]) == 0
    output = capsys.readouterr().out
    assert "approval_sha256=" in output
    assert "execution_started=false" in output


def test_d2c_approval_validation_cli_does_not_execute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    approval = _approval()
    destination = tmp_path / f"{approval.approval_record_id}.json"
    digest = write_review_approval(approval, destination)

    assert (
        main(
            [
                "validate",
                "--approval",
                str(destination),
                "--expected-sha256",
                digest,
                "--experiment-id",
                EXPERIMENT_ID,
                "--source-revision",
                SOURCE_REVISION,
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.endswith("approval_valid=true\nexecution_started=false\n")


def test_d2c_approval_module_has_no_model_or_benchmark_execution_path() -> None:
    source = Path("evaluation/d2c_approval.py").read_text(encoding="utf-8")

    assert "OpenAICompatibleProvider" not in source
    assert ".decide(" not in source
    assert "artifacts/live-eval/production-robustness" not in source
    assert "write benchmark" not in source.lower()
