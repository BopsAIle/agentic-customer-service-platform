from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evaluation.d2d.artifacts import (
    D2dAttempt,
    D2dEnvironment,
    D2dReleaseArtifactPublisher,
    D2dSummary,
    validate_published_bundle,
)
from evaluation.d2d.release_runner import D2dEnvironmentNotReady, D2dReleaseRunner
from evaluation.d2d_approval import (
    D2D_D2C_SUMMARY_SHA256,
    D2D_DRY_RUN_ATTEMPTS_SHA256,
    D2D_DRY_RUN_RECORDED_SOURCE,
    D2D_DRY_RUN_SUMMARY_SHA256,
    D2dEnvironmentFreeze,
    D2dProspectiveApproval,
    consume_approval,
    model_sha256,
    safe_configuration_sha256,
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
    canonical_d2d_contract,
)

SOURCE = "a" * 40
EXPERIMENT = "d2d_m6_34_release_gate_20260822T120000Z"


def _freeze(source: str = SOURCE) -> D2dEnvironmentFreeze:
    return D2dEnvironmentFreeze(
        freeze_record_id="d2d-release-test",
        frozen_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
        experiment_id=EXPERIMENT,
        source_revision=source,
        contract_version=D2D_CONTRACT_VERSION,
        contract_sha256=D2D_CONTRACT_SHA256,
        schedule_version=D2D_SCHEDULE_VERSION,
        schedule_sha256=D2D_SCHEDULE_SHA256,
        fault_matrix_version=D2D_FAULT_MATRIX_VERSION,
        fault_matrix_sha256=D2D_FAULT_MATRIX_SHA256,
        configuration_sha256=safe_configuration_sha256({"provider": "deterministic_integration"}),
        compose_config_sha256="b" * 64,
        compose_files=("docker-compose.yml", "docker-compose.integration.yml"),
        compose_project="d2d-release-test",
        required_services=("db", "qdrant", "demo-setup", "backend", "frontend", "jaeger"),
        image_identities={"backend": "backend@sha256:" + "c" * 64},
        toolchain={"docker": "29.7.2"},
        alembic_head=D2D_ALEMBIC_HEAD,
    )


def _approval(freeze: D2dEnvironmentFreeze, source: str = SOURCE) -> D2dProspectiveApproval:
    return D2dProspectiveApproval(
        reviewer_identity="release-hardening-owner",
        approved_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
        approval_record_id="d2d-release-test",
        experiment_id=EXPERIMENT,
        source_revision=source,
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


def _release_bundle() -> tuple[D2dEnvironment, list[D2dAttempt], D2dSummary]:
    environment = D2dEnvironment(
        source_sha=SOURCE,
        execution_mode="prospective_release",
        approval_status="approved",
        safe_configuration_hash="a" * 64,
        compose_project="d2d-release-test",
        required_services=("db", "backend"),
        alembic_head_expected=D2D_ALEMBIC_HEAD,
        alembic_head_actual=D2D_ALEMBIC_HEAD,
    )
    attempts = [
        D2dAttempt(
            ordinal=index,
            phase=scenario.phase_id,
            scenario_id=scenario.scenario_id,
            execution_mode="prospective_release",
            execution_path="deterministic_harness",
            status="PASS",
            duration_ms=1,
            mutation_count=0,
            duplicate_count=0,
            unauthorized_mutation_count=0,
            confirmation_bypass_count=0,
        )
        for index, scenario in enumerate(canonical_d2d_contract().scenarios, start=1)
    ]
    summary = D2dSummary(
        status="COMPLETE",
        execution_mode="prospective_release",
        approval_status="approved",
        classification="D2D_RELEASE_GATE_PASS",
        dimensions={"RUN_COMPLETENESS": "PASS"},
        scenario_count=18,
        phase_count=8,
        fault_count=6,
        same_action_concurrency={"attempts": 16, "rounds": 3, "committed_effects": [1, 1, 1]},
        independent_action_concurrency={"actions": 2, "rounds": 3, "committed_effects": [2, 2, 2]},
        release_gate="PROSPECTIVE_RELEASE_GATE",
    )
    return environment, attempts, summary


def test_consumption_is_atomic_and_duplicate_consumption_is_rejected(tmp_path: Path) -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    from evaluation.d2d_approval import _canonical_model_bytes

    approval_sha = hashlib.sha256(_canonical_model_bytes(approval)).hexdigest()
    lifecycle, lifecycle_sha = consume_approval(
        approval,
        freeze,
        approval_sha256=approval_sha,
        expected_source=SOURCE,
        execution_id="d2d-execution-1",
        consumed_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
        lifecycle_root=tmp_path,
    )
    assert lifecycle.state == "CONSUMED"
    assert lifecycle.execution_started is True
    assert lifecycle.consumed is True
    assert lifecycle.execution_id == "d2d-execution-1"
    assert len(lifecycle_sha) == 64
    with pytest.raises(FileExistsError):
        consume_approval(
            approval,
            freeze,
            approval_sha256=approval_sha,
            expected_source=SOURCE,
            execution_id="d2d-execution-2",
            consumed_at=datetime(2026, 8, 22, 12, 2, tzinfo=UTC),
            lifecycle_root=tmp_path,
        )


@pytest.mark.parametrize("expected_source", ["b" * 40])
def test_consumption_rejects_source_mismatch(tmp_path: Path, expected_source: str) -> None:
    freeze = _freeze()
    approval = _approval(freeze)
    from evaluation.d2d_approval import _canonical_model_bytes

    with pytest.raises(ValueError, match="D2D_SOURCE_BINDING_INVALID"):
        consume_approval(
            approval,
            freeze,
            approval_sha256=hashlib.sha256(_canonical_model_bytes(approval)).hexdigest(),
            expected_source=expected_source,
            execution_id="d2d-execution-1",
            consumed_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
            lifecycle_root=tmp_path,
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("approval_update", "expected_error"),
    [
        ({"contract_sha256": "c" * 64}, "D2D_CONTRACT_BINDING_INVALID"),
        ({"environment_freeze_sha256": "c" * 64}, "D2D_ENVIRONMENT_FREEZE_BINDING_INVALID"),
    ],
)
def test_consumption_rejects_contract_and_environment_mismatch(
    tmp_path: Path, approval_update: dict[str, str], expected_error: str
) -> None:
    freeze = _freeze()
    approval = _approval(freeze).model_copy(update=approval_update)
    from evaluation.d2d_approval import _canonical_model_bytes

    with pytest.raises(ValueError, match=expected_error):
        consume_approval(
            approval,
            freeze,
            approval_sha256=hashlib.sha256(_canonical_model_bytes(approval)).hexdigest(),
            expected_source=SOURCE,
            execution_id="d2d-execution-1",
            consumed_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
            lifecycle_root=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_release_artifacts_are_approved_and_non_overwriting(tmp_path: Path) -> None:
    environment, attempts, summary = _release_bundle()
    publisher = D2dReleaseArtifactPublisher(tmp_path)
    path, hashes = publisher.publish(
        "d2d_release_test",
        environment,
        attempts,
        summary,
        "prospective release\n",
        approval_sha256="d" * 64,
        execution_id="d2d-execution-1",
    )
    assert validate_published_bundle(path) == hashes
    manifest = (path / "manifest.json").read_text()
    assert '"approval_consumed":true' in manifest
    with pytest.raises(FileExistsError):
        publisher.publish(
            "d2d_release_test",
            environment,
            attempts,
            summary,
            "repeat\n",
            approval_sha256="d" * 64,
            execution_id="d2d-execution-2",
        )


def test_release_runner_does_not_consume_when_environment_is_unavailable(tmp_path: Path) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    from evaluation.d2d_approval import write_approval, write_environment_freeze

    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    def unavailable(_: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "unavailable")

    with pytest.raises(D2dEnvironmentNotReady):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=unavailable,
        ).run()
    assert not (tmp_path / "lifecycle").exists()
    assert approval_path.read_bytes() == approval_path.read_bytes()
    assert hashlib.sha256(approval_path.read_bytes()).hexdigest() == approval_sha


def test_release_runner_requires_an_approval(tmp_path: Path) -> None:
    runner = D2dReleaseRunner(
        approval_path=tmp_path / "missing-approval.json",
        approval_sha256="a" * 64,
        environment_path=tmp_path / "missing-environment.json",
        environment_sha256="b" * 64,
        artifact_root=tmp_path / "release",
        lifecycle_root=tmp_path / "lifecycle",
    )
    with pytest.raises(FileNotFoundError):
        runner.run()


def test_release_runner_consumes_once_and_publishes_release_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    class FakeStack:
        def clean(self) -> None:
            pass

        def run(self, _: tuple[str, ...], *, timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, "", "")

        def frontend_url(self) -> str:
            return "http://127.0.0.1:1"

        def database_scalar(self, _: str) -> str:
            return D2D_ALEMBIC_HEAD

    def available(_: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(
        "evaluation.d2d.release_runner.wait_for_ready", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "evaluation.d2d.release_runner.execute_frozen_contract",
        lambda **_kwargs: (_release_bundle()[1], _release_bundle()[2]),
    )
    runner = D2dReleaseRunner(
        approval_path=approval_path,
        approval_sha256=approval_sha,
        environment_path=freeze_path,
        environment_sha256=freeze_sha,
        artifact_root=tmp_path / "release",
        lifecycle_root=tmp_path / "lifecycle",
        command_runner=available,
        stack_factory=lambda _: FakeStack(),
    )
    run_id, artifact_path, _ = runner.run()
    assert run_id == EXPERIMENT
    assert (artifact_path / "summary.json").read_text().find('"prospective_release"') >= 0
    assert (artifact_path / "manifest.json").read_text().find('"approval_consumed":true') >= 0
    assert len(list((tmp_path / "lifecycle").glob("*.json"))) == 3
