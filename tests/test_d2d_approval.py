from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evaluation.d2d.images import D2dImageIdentity
from evaluation.d2d_approval import (
    D2D_APPROVAL_RECORD_SCHEMA_VERSION,
    D2D_D2C_EXPERIMENT_ID,
    D2D_D2C_SUMMARY_SHA256,
    D2D_DRY_RUN_ATTEMPTS_SHA256,
    D2D_DRY_RUN_ID,
    D2D_DRY_RUN_RECORDED_SOURCE,
    D2D_DRY_RUN_SUMMARY_SHA256,
    D2dEnvironmentFreeze,
    D2dEnvironmentImageValidationError,
    D2dProspectiveApproval,
    create_approval,
    load_approval,
    load_environment_freeze,
    model_sha256,
    safe_configuration_sha256,
    validate_approval,
    write_approval,
    write_environment_freeze,
)
from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    D2D_ARTIFACT_SCHEMA_VERSION,
    D2D_CONTRACT_SHA256,
    D2D_CONTRACT_VERSION,
    D2D_FAULT_MATRIX_SHA256,
    D2D_FAULT_MATRIX_VERSION,
    D2D_SCHEDULE_SHA256,
    D2D_SCHEDULE_VERSION,
)

SOURCE = "a" * 40
EXPERIMENT = "d2d_m6_34_release_gate_20260822T120000Z"


def _freeze() -> D2dEnvironmentFreeze:
    return D2dEnvironmentFreeze(
        freeze_record_id="d2d-review-test",
        frozen_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
        experiment_id=EXPERIMENT,
        source_revision=SOURCE,
        contract_version=D2D_CONTRACT_VERSION,
        contract_sha256=D2D_CONTRACT_SHA256,
        schedule_version=D2D_SCHEDULE_VERSION,
        schedule_sha256=D2D_SCHEDULE_SHA256,
        fault_matrix_version=D2D_FAULT_MATRIX_VERSION,
        fault_matrix_sha256=D2D_FAULT_MATRIX_SHA256,
        configuration_sha256=safe_configuration_sha256({"provider": "deterministic_integration"}),
        compose_config_sha256="b" * 64,
        compose_files=("docker-compose.yml", "docker-compose.integration.yml"),
        compose_project="d2d-review-test",
        required_services=("db", "qdrant", "demo-setup", "backend", "frontend", "jaeger"),
        image_identities={"backend": "sha256:" + "c" * 64},
        toolchain={"docker": "29.7.2"},
        alembic_head=D2D_ALEMBIC_HEAD,
    )


def _approval(freeze: D2dEnvironmentFreeze) -> D2dProspectiveApproval:
    return D2dProspectiveApproval(
        reviewer_identity="release-hardening-owner",
        approved_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
        approval_record_id="d2d-review-test",
        experiment_id=EXPERIMENT,
        source_revision=SOURCE,
        contract_version=D2D_CONTRACT_VERSION,
        contract_sha256=D2D_CONTRACT_SHA256,
        schedule_version=D2D_SCHEDULE_VERSION,
        schedule_sha256=D2D_SCHEDULE_SHA256,
        fault_matrix_version=D2D_FAULT_MATRIX_VERSION,
        fault_matrix_sha256=D2D_FAULT_MATRIX_SHA256,
        artifact_schema=D2D_ARTIFACT_SCHEMA_VERSION,
        alembic_head=D2D_ALEMBIC_HEAD,
        environment_freeze_record_id=freeze.freeze_record_id,
        environment_freeze_sha256=model_sha256(freeze),
        configuration_sha256=freeze.configuration_sha256,
        compose_config_sha256=freeze.compose_config_sha256,
        compose_project=freeze.compose_project,
        image_identities=freeze.image_identities,
        required_services=freeze.required_services,
        d2c_prerequisite_summary_sha256=D2D_D2C_SUMMARY_SHA256,
        m6_32_dry_run_recorded_source=D2D_DRY_RUN_RECORDED_SOURCE,
        m6_32_dry_run_summary_sha256=D2D_DRY_RUN_SUMMARY_SHA256,
        m6_32_dry_run_attempts_sha256=D2D_DRY_RUN_ATTEMPTS_SHA256,
    )


def _fully_pinned_freeze() -> D2dEnvironmentFreeze:
    freeze = _freeze()
    identities = {
        service: D2dImageIdentity(
            reference=f"d2d-test-{service}:frozen@sha256:{digest}",
            image_digest=digest,
            source="test",
            resolution_method="local_immutable_digest",
        )
        for service, digest in {
            "db": "1" * 64,
            "qdrant": "2" * 64,
            "demo-setup": "3" * 64,
            "backend": "4" * 64,
            "frontend": "5" * 64,
            "jaeger": "6" * 64,
        }.items()
    }
    return freeze.model_copy(update={"image_identities": identities})


def _matching_image_inspector(
    command: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    digest = command[-1].rsplit("@sha256:", 1)[-1]
    return subprocess.CompletedProcess(
        command,
        0,
        json.dumps([{"Id": f"sha256:{digest}"}]),
        "",
    )


def test_canonical_freeze_and_approval_round_trip_is_immutable(tmp_path: Path) -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    freeze_path = tmp_path / "d2d-review-test.environment-freeze.json"
    approval_path = tmp_path / "d2d-review-test.json"
    freeze_sha = write_environment_freeze(freeze, freeze_path)
    approval_sha = write_approval(approval, approval_path)
    assert load_environment_freeze(freeze_path, expected_sha256=freeze_sha) == freeze
    assert load_approval(approval_path, expected_sha256=approval_sha) == approval
    with pytest.raises(FileExistsError):
        write_approval(approval, approval_path)


def test_validation_rejects_source_contract_schedule_fault_and_environment_drift() -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    validate_approval(approval, freeze, expected_source=SOURCE)
    for field, value in (
        ("source_revision", "d" * 40),
        ("contract_sha256", "d" * 64),
        ("schedule_sha256", "d" * 64),
        ("fault_matrix_sha256", "d" * 64),
        ("environment_freeze_sha256", "d" * 64),
        ("same_action_concurrency", 8),
        ("automatic_retry_count", 1),
    ):
        changed = approval.model_copy(update={field: value})
        with pytest.raises(ValueError):
            validate_approval(changed, freeze, expected_source=SOURCE)


def test_approval_rejects_wrong_dry_run_evidence() -> None:
    freeze = _freeze()
    with pytest.raises(ValueError, match="D2D_M6_32_SUMMARY_MISMATCH"):
        payload = _approval(freeze).model_dump(mode="json")
        payload["m6_32_dry_run_summary_sha256"] = "e" * 64
        D2dProspectiveApproval.model_validate(payload)


def test_approval_never_starts_execution() -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    assert approval.record_schema_version == D2D_APPROVAL_RECORD_SCHEMA_VERSION
    assert approval.execution_started is False
    assert approval.consumed is False
    assert D2D_D2C_EXPERIMENT_ID in approval.d2c_prerequisite_experiment_id
    assert approval.m6_32_dry_run_id == D2D_DRY_RUN_ID


def test_missing_frozen_image_prevents_approval_creation(tmp_path: Path) -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    destination = tmp_path / "approval.json"

    with pytest.raises(D2dEnvironmentImageValidationError, match="IMAGE_UNAVAILABLE"):
        create_approval(
            approval,
            freeze,
            destination,
            expected_source=SOURCE,
            image_inspector=_matching_image_inspector,
        )
    assert not destination.exists()


def test_frozen_image_digest_mismatch_prevents_approval_creation(tmp_path: Path) -> None:
    freeze = _fully_pinned_freeze()
    approval = _approval(freeze)
    destination = tmp_path / "approval.json"

    def mismatch(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command[-1].startswith("d2d-test-frontend:"):
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"Id": "sha256:" + "f" * 64}]), ""
            )
        return _matching_image_inspector(command)

    with pytest.raises(D2dEnvironmentImageValidationError, match="DIGEST_MISMATCH"):
        create_approval(
            approval,
            freeze,
            destination,
            expected_source=SOURCE,
            image_inspector=mismatch,
        )
    assert not destination.exists()


def test_mutable_frozen_image_prevents_approval_creation(tmp_path: Path) -> None:
    pinned = _fully_pinned_freeze()
    freeze = pinned.model_copy(
        update={"image_identities": {**pinned.image_identities, "backend": "backend:latest"}}
    )
    approval = _approval(freeze)
    destination = tmp_path / "approval.json"

    with pytest.raises(D2dEnvironmentImageValidationError, match="IMAGE_INVALID"):
        create_approval(
            approval,
            freeze,
            destination,
            expected_source=SOURCE,
            image_inspector=_matching_image_inspector,
        )
    assert not destination.exists()


def test_valid_local_frozen_images_create_approval(tmp_path: Path) -> None:
    freeze = _fully_pinned_freeze()
    approval = _approval(freeze)
    destination = tmp_path / "d2d-review-test.json"

    approval_sha = create_approval(
        approval,
        freeze,
        destination,
        expected_source=SOURCE,
        image_inspector=_matching_image_inspector,
    )

    assert load_approval(destination, expected_sha256=approval_sha) == approval
    assert approval.execution_started is False
    assert approval.consumed is False
