from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from evaluation.d2d.artifacts import (
    D2dArtifactPublisher,
    D2dAttempt,
    D2dEnvironment,
    D2dSummary,
    safe_configuration_hash,
    validate_published_bundle,
)
from evaluation.d2d.concurrency import run_overlapping
from evaluation.d2d.faults import FaultController, FaultControllerError
from evaluation.d2d.runner import D2dDryRunRunner
from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    D2D_CONTRACT_SHA256,
    D2D_CONTRACT_VERSION,
    D2D_FAULT_MATRIX_SHA256,
    D2D_FAULT_MATRIX_VERSION,
    D2D_SCHEDULE_SHA256,
    D2D_SCHEDULE_VERSION,
    canonical_d2d_contract,
)


def _environment() -> D2dEnvironment:
    return D2dEnvironment(
        source_sha="a" * 40,
        safe_configuration_hash=safe_configuration_hash({"provider": "deterministic_integration"}),
        compose_project="d2d-test",
        required_services=("db", "backend"),
        alembic_head_expected=D2D_ALEMBIC_HEAD,
        alembic_head_actual=D2D_ALEMBIC_HEAD,
    )


def _attempts() -> list[D2dAttempt]:
    return [
        D2dAttempt(
            ordinal=index,
            phase=scenario.phase_id,
            scenario_id=scenario.scenario_id,
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


def _summary() -> D2dSummary:
    return D2dSummary(
        status="COMPLETE",
        classification="D2D_DRY_RUN_PASS",
        dimensions={"RUN_COMPLETENESS": "PASS"},
        scenario_count=18,
        phase_count=8,
        fault_count=6,
        same_action_concurrency={"attempts": 16, "rounds": 3, "committed_effects": [1, 1, 1]},
        independent_action_concurrency={"actions": 2, "rounds": 3, "committed_effects": [2, 2, 2]},
    )


def test_concurrency_helper_actually_overlaps_all_workers() -> None:
    lock = threading.Lock()
    active = 0
    maximum = 0

    def operation(_: int, __: threading.Barrier) -> int:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return 1

    results = run_overlapping(16, operation)

    assert len(results) == 16
    assert all(result.started and result.error_type is None for result in results)
    assert maximum > 1


def test_concurrency_helper_retains_worker_exceptions_without_retry() -> None:
    calls: list[int] = []

    def operation(ordinal: int, _: threading.Barrier) -> int:
        calls.append(ordinal)
        if ordinal == 3:
            raise RuntimeError("fixture failure")
        return ordinal

    results = run_overlapping(8, operation)

    assert len(results) == 8
    assert len(calls) == 8
    assert results[3].error_type == "RuntimeError"


def test_fault_controller_restores_after_body_failure() -> None:
    events: list[str] = []
    controller = FaultController(
        "fixture", lambda: events.append("activate"), lambda: events.append("restore")
    )
    with pytest.raises(RuntimeError):
        with controller:
            events.append("body")
            raise RuntimeError("body failure")
    assert events == ["activate", "body", "restore"]
    assert controller.active is False


def test_fault_controller_surfaces_restore_failure_without_retry() -> None:
    calls = 0

    def restore() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("restore failure")

    with pytest.raises(FaultControllerError, match="D2D_FAULT_RESTORE_FAILED:fixture"):
        with FaultController("fixture", lambda: None, restore):
            pass
    assert calls == 1


def test_artifact_publication_is_bounded_and_non_overwriting(tmp_path: Path) -> None:
    publisher = D2dArtifactPublisher(tmp_path)
    path, hashes = publisher.publish(
        "d2d_dryrun_test",
        _environment(),
        _attempts(),
        _summary(),
        "dry-run; not approved\n",
    )

    assert path.is_dir()
    assert set(hashes) == set(D2dArtifactPublisher.FILES)
    assert validate_published_bundle(path) == hashes
    with pytest.raises(FileExistsError):
        publisher.publish("d2d_dryrun_test", _environment(), _attempts(), _summary(), "repeat\n")


def test_artifact_rejects_formal_release_gate_marker(tmp_path: Path) -> None:
    publisher = D2dArtifactPublisher(tmp_path)
    path, _ = publisher.publish(
        "d2d_dryrun_test",
        _environment(),
        _attempts(),
        _summary(),
        "dry-run\n",
    )
    summary = json.loads((path / "summary.json").read_text())
    summary["release_gate"] = "D2D_RELEASE_GATE_PASS"
    (path / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="D2D_ARTIFACT_HASH_MISMATCH:summary.json"):
        validate_published_bundle(path)


def test_artifact_rejects_sensitive_fields(tmp_path: Path) -> None:
    publisher = D2dArtifactPublisher(tmp_path)
    with pytest.raises(ValueError, match="D2D_PRIVACY_VIOLATION"):
        publisher.publish(
            "d2d_dryrun_test",
            _environment(),
            [
                item.model_copy(update={"details": {"raw_user_text": "secret"}})
                for item in _attempts()
            ],
            _summary(),
            "dry-run\n",
        )


def test_no_compose_dry_run_binds_frozen_contract_and_is_non_approved(tmp_path: Path) -> None:
    run_id, path, _ = D2dDryRunRunner(artifact_root=tmp_path, compose=False).run()
    summary = json.loads((path / "summary.json").read_text())
    environment = json.loads((path / "environment.json").read_text())

    assert run_id.startswith("d2d_dryrun_m6_32_")
    assert summary["classification"] == "D2D_DRY_RUN_PASS"
    assert summary["release_gate"] == "NON_APPROVED_DRY_RUN"
    assert environment["contract_version"] == D2D_CONTRACT_VERSION
    assert environment["contract_sha"] == D2D_CONTRACT_SHA256
    assert environment["schedule_version"] == D2D_SCHEDULE_VERSION
    assert environment["schedule_sha"] == D2D_SCHEDULE_SHA256
    assert environment["fault_matrix_version"] == D2D_FAULT_MATRIX_VERSION
    assert environment["fault_matrix_sha"] == D2D_FAULT_MATRIX_SHA256
    assert environment["approval_status"] == "not_approved"
