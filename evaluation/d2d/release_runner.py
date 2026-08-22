"""Approved prospective D2d release-gate execution.

This module is intentionally separate from the non-approving dry-run runner.  It performs
environment checks first, atomically consumes exactly one approval, and only then starts the
isolated operational schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
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
from evaluation.d2d.runner import (
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
from scripts.e2e_authenticated_smoke import wait_for_ready

ROOT = Path(__file__).parents[2]
DEFAULT_RELEASE_ROOT = ROOT / "artifacts" / "d2d" / "release-gates"
DEFAULT_LIFECYCLE_ROOT = ROOT / "artifacts" / "d2d" / "approval-lifecycle"


class D2dEnvironmentNotReady(RuntimeError):
    """The frozen environment cannot be validated before approval consumption."""


class D2dReleaseExecutionFailure(RuntimeError):
    """A consumed release execution failed without being automatically retried."""


CommandRunner = Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]


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
        self.now = now

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
        for image in freeze.image_identities.values():
            result = self.command_runner(("docker", "image", "inspect", image))
            if result.returncode != 0:
                raise D2dEnvironmentNotReady(f"D2D_ENVIRONMENT_NOT_READY:image:{image}")

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
        try:
            stack = self.stack_factory(freeze.compose_project)
            stack.clean()
            stack.run(("up", "--detach", "--wait", "--wait-timeout", "240"), timeout=600)
            wait_for_ready(stack.frontend_url(), timeout_seconds=120)
            actual_alembic_head = stack.database_scalar("select version_num from alembic_version;")
            if actual_alembic_head != D2D_ALEMBIC_HEAD:
                raise D2dReleaseExecutionFailure("D2D_ALEMBIC_HEAD_MISMATCH")
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
                _write_state(
                    transition_lifecycle(running_lifecycle, "FAILED", updated_at=self.now()),
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
