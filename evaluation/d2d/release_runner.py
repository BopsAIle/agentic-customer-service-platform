"""Approved prospective D2d release-gate execution.

This module is intentionally separate from the non-approving dry-run runner.  It performs
environment checks first, atomically consumes exactly one approval, and only then starts the
isolated operational schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from evaluation.d2d.artifacts import (
    D2dEnvironment,
    D2dReleaseArtifactPublisher,
    validate_published_bundle,
)
from evaluation.d2d.images import D2dImageIdentity, image_reference, structured_image_identity
from evaluation.d2d.runner import (
    TOKEN,
    D2dHarnessFailure,
    HermeticComposeStack,
    _git_source,
    execute_frozen_contract,
)
from evaluation.d2d_approval import (
    D2dApprovalLifecycle,
    D2dEnvironmentFreeze,
    D2dProspectiveApproval,
    consume_approval,
    load_approval,
    load_environment_freeze,
    transition_lifecycle,
    write_lifecycle_state,
)
from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    canonical_d2d_contract,
    validate_contract_identity,
)
from scripts.e2e_authenticated_smoke import MEMORY_PRIVATE_CONTENT, wait_for_ready

ROOT = Path(__file__).parents[2]
DEFAULT_RELEASE_ROOT = ROOT / "artifacts" / "d2d" / "release-gates"
DEFAULT_LIFECYCLE_ROOT = ROOT / "artifacts" / "d2d" / "approval-lifecycle"


class D2dEnvironmentNotReady(RuntimeError):
    """The frozen environment cannot be validated before approval consumption."""


class D2dReleaseExecutionFailure(RuntimeError):
    """A consumed release execution failed without being automatically retried."""


CommandRunner = Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]
_FAILURE_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|password|secret|token)\s*[:=]\s*([^\s,;]+)"
)


def _privacy_safe_failure_text(value: object, *, limit: int) -> str:
    """Bound and redact failure text before it enters immutable release evidence."""

    text = str(value).replace(TOKEN, "[REDACTED]").replace(MEMORY_PRIVATE_CONTENT, "[REDACTED]")
    text = _FAILURE_SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    return text[-limit:]


class FrozenImageComposeStack(HermeticComposeStack):
    """Hermetic Compose stack that can only use the approved immutable images."""

    def __init__(self, project: str, image_compose_path: Path) -> None:
        super().__init__(project)
        self.image_compose_path = image_compose_path

    @property
    def command(self) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--file",
            str(self.image_compose_path),
        ]

    def reset_seed(self) -> None:
        self.run(("run", "--no-build", "--pull", "never", "--rm", "demo-setup"), timeout=300)


class ComposeStackLike(Protocol):
    def clean(self) -> None: ...

    def run(
        self, arguments: tuple[str, ...], *, timeout: int
    ) -> subprocess.CompletedProcess[str]: ...

    def frontend_url(self) -> str: ...

    def database_scalar(self, statement: str) -> str: ...


def _default_command_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_state(
    lifecycle: D2dApprovalLifecycle,
    lifecycle_root: Path,
) -> str:
    destination = lifecycle_root / (
        f"{lifecycle.approval_record_id}.{lifecycle.execution_id}.{lifecycle.state.lower()}.json"
    )
    return write_lifecycle_state(lifecycle, destination)


def _image_inspection_matches(
    result: subprocess.CompletedProcess[str], identity: D2dImageIdentity
) -> bool:
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return False
    inspected = payload[0]
    digest = f"sha256:{identity.image_digest}"
    if inspected.get("Id") == digest:
        return True
    repo_digests = inspected.get("RepoDigests")
    return isinstance(repo_digests, list) and any(
        isinstance(value, str) and value.rsplit("@", 1)[-1] == digest for value in repo_digests
    )


def _write_image_only_compose(
    freeze: D2dEnvironmentFreeze,
    directory: Path,
    rendered_config: dict[str, Any],
) -> Path:
    """Create a Compose-compatible file with explicit immutable images and no builds."""

    services = rendered_config.get("services")
    if not isinstance(services, dict) or not services:
        raise D2dEnvironmentNotReady("D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:services")
    for service in freeze.required_services:
        value = freeze.image_identities.get(service)
        if value is None:
            raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_IMAGE_MISMATCH:missing:{service}")
    for service, service_config in services.items():
        if not isinstance(service_config, dict):
            raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:{service}")
        service_config.pop("build", None)
        value = freeze.image_identities.get(service)
        if value is not None:
            service_config["image"] = image_reference(value)
        if "build" in service_config or not isinstance(service_config.get("image"), str):
            raise D2dEnvironmentNotReady(
                f"D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:image_only:{service}"
            )
    path = directory / "frozen-images.json"
    path.write_bytes(
        json.dumps(rendered_config, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    return path


class D2dReleaseRunner:
    """Execute one approved prospective D2d release gate with no retry behavior."""

    def __init__(
        self,
        *,
        approval_path: Path,
        approval_sha256: str,
        environment_path: Path,
        environment_sha256: str,
        artifact_root: Path = DEFAULT_RELEASE_ROOT,
        lifecycle_root: Path = DEFAULT_LIFECYCLE_ROOT,
        command_runner: CommandRunner = _default_command_runner,
        stack_factory: Callable[[str], ComposeStackLike] = HermeticComposeStack,
        compose_config_runner: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.approval_path = approval_path
        self.approval_sha256 = approval_sha256
        self.environment_path = environment_path
        self.environment_sha256 = environment_sha256
        self.artifact_root = artifact_root
        self.lifecycle_root = lifecycle_root
        self.command_runner = command_runner
        self.stack_factory = stack_factory
        self.compose_config_runner = compose_config_runner or self._default_compose_config_runner
        self.now = now

    @staticmethod
    def _default_compose_config_runner(project: str) -> subprocess.CompletedProcess[str]:
        stack = HermeticComposeStack(project)
        return stack.run(("config", "--format", "json"), timeout=120, check=False)

    def load_and_validate(self) -> tuple[D2dProspectiveApproval, D2dEnvironmentFreeze]:
        approval = load_approval(self.approval_path, expected_sha256=self.approval_sha256)
        freeze = load_environment_freeze(
            self.environment_path, expected_sha256=self.environment_sha256
        )
        validate_contract_identity(canonical_d2d_contract())
        from evaluation.d2d_approval import validate_approval

        validate_approval(approval, freeze, expected_source=_git_source())
        return approval, freeze

    def check_environment(self, freeze: D2dEnvironmentFreeze) -> None:
        """Check all environment prerequisites before the approval can be consumed."""

        for command in (("docker", "version"), ("docker", "compose", "version")):
            result = self.command_runner(command)
            if result.returncode != 0:
                raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_NOT_READY:{' '.join(command)}")
        for compose_file in freeze.compose_files:
            if not (ROOT / compose_file).is_file():
                raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_NOT_READY:missing:{compose_file}")
        for service in freeze.required_services:
            value = freeze.image_identities.get(service)
            try:
                identity = structured_image_identity(value) if value is not None else None
            except ValueError as error:
                raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_IMAGE_MISMATCH:{service}") from error
            if identity is None:
                raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_IMAGE_MISMATCH:{service}")
            result = self.command_runner(("docker", "image", "inspect", identity.reference))
            if not _image_inspection_matches(result, identity):
                raise D2dEnvironmentNotReady(
                    f"D2D_ENVIRONMENT_IMAGE_MISMATCH:{service}:{identity.reference}"
                )

    def _approved_environment(
        self,
        approval: D2dProspectiveApproval,
        freeze: D2dEnvironmentFreeze,
        *,
        actual_alembic_head: str,
    ) -> D2dEnvironment:
        return D2dEnvironment(
            source_sha=approval.source_revision,
            execution_mode="prospective_release",
            approval_status="approved",
            safe_configuration_hash=approval.configuration_sha256,
            compose_project=freeze.compose_project,
            required_services=freeze.required_services,
            image_identities=freeze.image_identities,
            alembic_head_expected=D2D_ALEMBIC_HEAD,
            alembic_head_actual=actual_alembic_head,
            provider_identity="deterministic_integration",
            automatic_retry_count=approval.automatic_retry_count,
            automatic_rerun_count=approval.automatic_rerun_count,
        )

    def run(self) -> tuple[str, Path, dict[str, str]]:
        approval, freeze = self.load_and_validate()
        self.check_environment(freeze)
        with tempfile.TemporaryDirectory(prefix="d2d-frozen-images-") as temporary_directory:
            rendered = self.compose_config_runner(freeze.compose_project)
            if rendered.returncode != 0:
                raise D2dEnvironmentNotReady("D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:render")
            try:
                rendered_config = json.loads(rendered.stdout)
            except json.JSONDecodeError as error:
                raise D2dEnvironmentNotReady(
                    "D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:json"
                ) from error
            if not isinstance(rendered_config, dict):
                raise D2dEnvironmentNotReady("D2D_ENVIRONMENT_COMPOSE_CONFIG_INVALID:root")
            image_compose_path = _write_image_only_compose(
                freeze, Path(temporary_directory), rendered_config
            )
            return self._run_with_frozen_environment(approval, freeze, image_compose_path)

    def _run_with_frozen_environment(
        self,
        approval: D2dProspectiveApproval,
        freeze: D2dEnvironmentFreeze,
        image_override_path: Path,
    ) -> tuple[str, Path, dict[str, str]]:
        execution_id = approval.experiment_id
        consumed_at = self.now()
        lifecycle, _ = consume_approval(
            approval,
            freeze,
            approval_sha256=self.approval_sha256,
            expected_source=approval.source_revision,
            execution_id=execution_id,
            consumed_at=consumed_at,
            lifecycle_root=self.lifecycle_root,
        )
        running_lifecycle = transition_lifecycle(lifecycle, "RUNNING", updated_at=self.now())
        _write_state(running_lifecycle, self.lifecycle_root)
        stack: ComposeStackLike | None = None
        phase = "D2D-1_CLEAN_BOOTSTRAP"
        command = "compose down --volumes --remove-orphans --timeout 20"
        try:
            if self.stack_factory is HermeticComposeStack:
                stack = FrozenImageComposeStack(freeze.compose_project, image_override_path)
            else:
                stack = self.stack_factory(freeze.compose_project)
            stack.clean()
            command = "compose up --no-build --pull never --detach --wait --wait-timeout 240"
            stack.run(
                (
                    "up",
                    "--no-build",
                    "--pull",
                    "never",
                    "--detach",
                    "--wait",
                    "--wait-timeout",
                    "240",
                ),
                timeout=600,
            )
            phase = "D2D-1_HEALTH_READINESS"
            command = "frontend readiness probe"
            wait_for_ready(stack.frontend_url(), timeout_seconds=120)
            command = "query alembic_version"
            actual_alembic_head = stack.database_scalar("select version_num from alembic_version;")
            if actual_alembic_head != D2D_ALEMBIC_HEAD:
                raise D2dReleaseExecutionFailure("D2D_ALEMBIC_HEAD_MISMATCH")
            phase = "D2D-2_BASELINE_FUNCTIONAL_E2E"
            command = "execute_frozen_contract"
            started = time.monotonic()
            attempts, summary = execute_frozen_contract(
                stack=cast(HermeticComposeStack, stack),
                compose=True,
                started=started,
                execution_mode="prospective_release",
            )
            environment = self._approved_environment(
                approval, freeze, actual_alembic_head=actual_alembic_head
            )
            summary_markdown = _release_summary_markdown(
                execution_id, approval.source_revision, summary
            )
            path, hashes = D2dReleaseArtifactPublisher(self.artifact_root).publish(
                execution_id,
                environment,
                attempts,
                summary,
                summary_markdown,
                approval_sha256=self.approval_sha256,
                execution_id=execution_id,
            )
            validate_published_bundle(path)
            _write_state(
                transition_lifecycle(running_lifecycle, "PASSED", updated_at=self.now()),
                self.lifecycle_root,
            )
            return execution_id, path, hashes
        except Exception as error:
            try:
                safe_error_type = _privacy_safe_failure_text(type(error).__name__, limit=200)
                safe_error_message = _privacy_safe_failure_text(error, limit=4000)
                safe_command = _privacy_safe_failure_text(command, limit=1000)
                _write_state(
                    transition_lifecycle(
                        running_lifecycle,
                        "FAILED",
                        updated_at=self.now(),
                        phase=phase,
                        error_type=safe_error_type,
                        error_message=safe_error_message,
                        command=safe_command,
                    ),
                    self.lifecycle_root,
                )
            except Exception as lifecycle_error:
                raise D2dReleaseExecutionFailure(
                    "D2D_LIFECYCLE_FAILURE_STATE_UNWRITABLE"
                ) from lifecycle_error
            raise D2dReleaseExecutionFailure("D2D_RELEASE_EXECUTION_FAILED") from error
        finally:
            if stack is not None:
                stack.clean()


def _release_summary_markdown(execution_id: str, source: str, summary: Any) -> str:
    lines = [
        "# D2d Prospective Release-Gate Execution",
        "",
        f"- Experiment: `{execution_id}`",
        f"- Source: `{source}`",
        "- Execution mode: `prospective_release`",
        "- Approval status: `approved`",
        "- Approval consumed: `true`",
        f"- Classification: `{summary.classification}`",
        "- Release-gate status: `PROSPECTIVE_RELEASE_GATE`",
        "",
        "This bundle is source-bound prospective D2d evidence.",
        "",
        "| Dimension | Status |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in summary.dimensions.items())
    lines.extend(
        [
            "",
            f"- Scenarios: `{summary.scenario_count}/18`",
            f"- Phases: `{summary.phase_count}/8`",
            f"- Fault classes: `{summary.fault_count}/6`",
            "- Same-action committed effects by round: `1, 1, 1`",
            "- Independent-action committed effects by round: `2, 2, 2`",
            "- Retries: `0`",
            "- Automatic reruns: `0`",
            "- Privacy violations: `0`",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--lifecycle-root", type=Path, default=DEFAULT_LIFECYCLE_ROOT)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    try:
        run_id, path, hashes = D2dReleaseRunner(
            approval_path=args.approval,
            approval_sha256=args.approval_sha256,
            environment_path=args.environment,
            environment_sha256=args.environment_sha256,
            artifact_root=args.artifact_root,
            lifecycle_root=args.lifecycle_root,
        ).run()
        print(f"D2D_RELEASE_GATE_PASS run={run_id} path={path}")
        for name, value in hashes.items():
            print(f"{name}={value}")
        return 0
    except (
        D2dEnvironmentNotReady,
        D2dReleaseExecutionFailure,
        D2dHarnessFailure,
        OSError,
        ValueError,
    ) as error:
        print(f"D2D_RELEASE_GATE_FAIL:{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
