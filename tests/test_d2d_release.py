from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Sequence
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
from evaluation.d2d.images import D2dImageIdentity
from evaluation.d2d.release_runner import (
    D2dEnvironmentNotReady,
    D2dReleaseExecutionFailure,
    D2dReleaseRunner,
    FrozenImageComposeStack,
    _write_image_only_compose,
)
from evaluation.d2d_approval import (
    D2D_D2C_SUMMARY_SHA256,
    D2D_DRY_RUN_ATTEMPTS_SHA256,
    D2D_DRY_RUN_RECORDED_SOURCE,
    D2D_DRY_RUN_SUMMARY_SHA256,
    D2dEnvironmentFreeze,
    D2dProspectiveApproval,
    consume_approval,
    load_lifecycle_state,
    model_sha256,
    safe_configuration_sha256,
    write_approval,
    write_environment_freeze,
    write_lifecycle_state,
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
    image_identities = {
        service: D2dImageIdentity(
            reference=f"d2d-test-{service}:latest@sha256:{digest}",
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
        image_identities=image_identities,
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


def _available_image_inspection(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    if command == ("docker", "compose", "up", "--help"):
        return subprocess.CompletedProcess(
            command,
            0,
            "--no-build --pull --no-deps --exit-code-from",
            "",
        )
    if command[:3] == ("docker", "image", "inspect"):
        reference = command[-1]
        digest = reference.rsplit("@sha256:", 1)[-1]
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps([{"Id": f"sha256:{digest}", "RepoDigests": [reference]}]),
            "",
        )
    return subprocess.CompletedProcess(command, 0, "", "")


def _rendered_compose_config() -> dict[str, object]:
    return {
        "services": {
            service: {"build": ".", "image": f"old-{service}:local"}
            for service in ("db", "qdrant", "demo-setup", "backend", "frontend", "jaeger")
        },
        "volumes": {"postgres_data": {}, "qdrant_data": {}},
    }


def test_frozen_image_identity_match_passes_environment_check() -> None:
    runner = D2dReleaseRunner(
        approval_path=Path("unused"),
        approval_sha256="a" * 64,
        environment_path=Path("unused"),
        environment_sha256="b" * 64,
        command_runner=_available_image_inspection,
    )
    runner.check_environment(_freeze())


def test_frozen_seed_command_uses_compose_compatible_no_build_no_pull_path() -> None:
    command = FrozenImageComposeStack.seed_arguments()

    assert command[0] == "up"
    assert "run" not in command
    assert "--no-build" in command
    assert command[command.index("--pull") + 1] == "never"
    assert "--no-deps" in command
    assert command[-1] == "demo-setup"


def test_incompatible_compose_cli_is_rejected_before_approval_consumption(
    tmp_path: Path,
) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    def incompatible(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command == ("docker", "compose", "up", "--help"):
            return subprocess.CompletedProcess(command, 0, "--build --pull", "")
        return _available_image_inspection(command)

    with pytest.raises(D2dEnvironmentNotReady, match="COMPOSE_CLI_INCOMPATIBLE"):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=incompatible,
        ).run()
    assert not (tmp_path / "lifecycle").exists()


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_frozen_image_mismatch_blocks_environment_check(service: str) -> None:
    freeze = _freeze()

    def mismatch(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ("docker", "image", "inspect") and command[-1].startswith(
            f"d2d-test-{service}"
        ):
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"Id": "sha256:" + "f" * 64}]), ""
            )
        return _available_image_inspection(command)

    runner = D2dReleaseRunner(
        approval_path=Path("unused"),
        approval_sha256="a" * 64,
        environment_path=Path("unused"),
        environment_sha256="b" * 64,
        command_runner=mismatch,
    )
    with pytest.raises(D2dEnvironmentNotReady, match="D2D_ENVIRONMENT_IMAGE_MISMATCH"):
        runner.check_environment(freeze)


def test_legacy_mutable_image_binding_is_rejected_before_consumption() -> None:
    freeze = _freeze().model_copy(update={"image_identities": {"backend": "backend:latest"}})
    runner = D2dReleaseRunner(
        approval_path=Path("unused"),
        approval_sha256="a" * 64,
        environment_path=Path("unused"),
        environment_sha256="b" * 64,
        command_runner=_available_image_inspection,
    )
    with pytest.raises(D2dEnvironmentNotReady, match="D2D_ENVIRONMENT_IMAGE_MISMATCH"):
        runner.check_environment(freeze)


def test_image_mismatch_does_not_consume_approval(tmp_path: Path) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    def mismatch(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ("docker", "image", "inspect"):
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"Id": "sha256:" + "f" * 64}]), ""
            )
        return _available_image_inspection(command)

    with pytest.raises(D2dEnvironmentNotReady, match="D2D_ENVIRONMENT_IMAGE_MISMATCH"):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=mismatch,
        ).run()
    assert not (tmp_path / "lifecycle").exists()


def test_invalid_rendered_compose_does_not_consume_approval(tmp_path: Path) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    with pytest.raises(D2dEnvironmentNotReady, match="D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID"):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=_available_image_inspection,
            compose_config_runner=lambda _: subprocess.CompletedProcess([], 0, "{}", ""),
        ).run()
    assert not (tmp_path / "lifecycle").exists()


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
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def clean(self) -> None:
            pass

        def run(
            self, arguments: tuple[str, ...], *, timeout: int
        ) -> subprocess.CompletedProcess[str]:
            self.calls.append(arguments)
            return subprocess.CompletedProcess([], 0, "", "")

        def frontend_url(self) -> str:
            return "http://127.0.0.1:1"

        def database_scalar(self, _: str) -> str:
            return D2D_ALEMBIC_HEAD

    monkeypatch.setattr(
        "evaluation.d2d.release_runner.wait_for_ready", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "evaluation.d2d.release_runner.execute_frozen_contract",
        lambda **_kwargs: (_release_bundle()[1], _release_bundle()[2]),
    )
    stack = FakeStack()
    runner = D2dReleaseRunner(
        approval_path=approval_path,
        approval_sha256=approval_sha,
        environment_path=freeze_path,
        environment_sha256=freeze_sha,
        artifact_root=tmp_path / "release",
        lifecycle_root=tmp_path / "lifecycle",
        command_runner=_available_image_inspection,
        compose_config_runner=lambda _: subprocess.CompletedProcess(
            [], 0, json.dumps(_rendered_compose_config()), ""
        ),
        stack_factory=lambda _: stack,
    )
    run_id, artifact_path, _ = runner.run()
    assert run_id == EXPERIMENT
    assert (artifact_path / "summary.json").read_text().find('"prospective_release"') >= 0
    assert (artifact_path / "manifest.json").read_text().find('"approval_consumed":true') >= 0
    assert stack.calls[0] == (
        "up",
        "--no-build",
        "--pull",
        "never",
        "--detach",
        "--wait",
        "--wait-timeout",
        "240",
    )
    assert len(list((tmp_path / "lifecycle").glob("*.json"))) == 3


def test_startup_failure_publishes_privacy_safe_diagnostics_and_cannot_reuse_approval(
    tmp_path: Path,
) -> None:
    source = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = _freeze(source)
    approval = _approval(freeze, source)
    approval_path = tmp_path / "d2d-release-test.json"
    freeze_path = tmp_path / "d2d-release-test.environment-freeze.json"
    approval_sha = write_approval(approval, approval_path)
    freeze_sha = write_environment_freeze(freeze, freeze_path)

    class FailingStack:
        def clean(self) -> None:
            pass

        def run(
            self, arguments: tuple[str, ...], *, timeout: int
        ) -> subprocess.CompletedProcess[str]:
            del arguments, timeout
            raise RuntimeError("password=top-secret token=d2d-dry-run-integration-token")

        def frontend_url(self) -> str:
            return "http://127.0.0.1:1"

        def database_scalar(self, _: str) -> str:
            return D2D_ALEMBIC_HEAD

    with pytest.raises(D2dReleaseExecutionFailure, match="D2D_RELEASE_EXECUTION_FAILED"):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=_available_image_inspection,
            compose_config_runner=lambda _: subprocess.CompletedProcess(
                [], 0, json.dumps(_rendered_compose_config()), ""
            ),
            stack_factory=lambda _: FailingStack(),
        ).run()

    failed_paths = list((tmp_path / "lifecycle").glob("*.failed.json"))
    assert len(failed_paths) == 1
    failed_path = failed_paths[0]
    failed = load_lifecycle_state(
        failed_path, expected_sha256=hashlib.sha256(failed_path.read_bytes()).hexdigest()
    )
    assert failed.state == "FAILED"
    assert failed.status == "FAILED"
    assert failed.phase == "D2D-1_CLEAN_BOOTSTRAP"
    assert failed.error_type == "RuntimeError"
    assert failed.error_message == "password=[REDACTED] token=[REDACTED]"
    assert failed.command == "compose up --no-build --pull never --detach --wait --wait-timeout 240"
    assert failed.source_sha == source
    assert failed.approval_sha256 == approval_sha
    assert failed.environment_sha == model_sha256(freeze)
    assert "top-secret" not in failed_path.read_text()
    with pytest.raises(FileExistsError):
        write_lifecycle_state(failed, failed_path)

    with pytest.raises(FileExistsError):
        D2dReleaseRunner(
            approval_path=approval_path,
            approval_sha256=approval_sha,
            environment_path=freeze_path,
            environment_sha256=freeze_sha,
            artifact_root=tmp_path / "release",
            lifecycle_root=tmp_path / "lifecycle",
            command_runner=_available_image_inspection,
            compose_config_runner=lambda _: subprocess.CompletedProcess(
                [], 0, json.dumps(_rendered_compose_config()), ""
            ),
            stack_factory=lambda _: FailingStack(),
        ).run()


def test_frozen_compose_file_pins_images_and_disables_build(tmp_path: Path) -> None:
    freeze = _freeze()
    compose_path = _write_image_only_compose(freeze, tmp_path, _rendered_compose_config())
    payload = json.loads(compose_path.read_text())
    assert all(service in payload["services"] for service in freeze.required_services)
    for service, service_config in payload["services"].items():
        identity = freeze.image_identities[service]
        assert isinstance(identity, D2dImageIdentity)
        assert service_config["image"].endswith(f"@sha256:{identity.image_digest}")
        assert "build" not in service_config
    stack = FrozenImageComposeStack(freeze.compose_project, compose_path)
    command = stack.command
    assert "--build" not in command
    assert str(compose_path) in command


def test_frozen_stack_bootstrap_never_builds_or_pulls() -> None:
    class RecordingStack(FrozenImageComposeStack):
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(
            self,
            arguments: Sequence[str],
            *,
            timeout: int = 300,
            check: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            del timeout, check
            self.calls.append(tuple(arguments))
            return subprocess.CompletedProcess([], 0, "", "")

    stack = RecordingStack()
    stack.reset_seed()

    assert stack.calls == [FrozenImageComposeStack.seed_arguments()]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is unavailable")
def test_frozen_compose_file_is_accepted_by_docker_compose_config(tmp_path: Path) -> None:
    freeze = _freeze()
    rendered = subprocess.run(
        (
            "docker",
            "compose",
            "--file",
            "docker-compose.yml",
            "--file",
            "docker-compose.integration.yml",
            "--env-file",
            ".env.example",
            "config",
            "--format",
            "json",
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    compose_path = _write_image_only_compose(freeze, tmp_path, json.loads(rendered.stdout))
    checked = subprocess.run(
        ("docker", "compose", "--file", str(compose_path), "config", "--format", "json"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    checked_config = json.loads(checked.stdout)
    assert all("build" not in service for service in checked_config["services"].values())
    for service, identity in freeze.image_identities.items():
        assert isinstance(identity, D2dImageIdentity)
        assert checked_config["services"][service]["image"] == identity.reference
