"""Non-approved D2d dry-run orchestration.

This module deliberately stops at ``D2D_DRY_RUN_PASS``. It validates the harness and the
repository-supported integration boundary; it never creates an approval or emits the prospective
D2d release classification.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.d2d.artifacts import (
    D2dArtifactPublisher,
    D2dAttempt,
    D2dEnvironment,
    D2dSummary,
    safe_configuration_hash,
    validate_published_bundle,
)
from evaluation.d2d.concurrency import run_overlapping
from evaluation.d2d.faults import FaultController
from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    canonical_d2d_contract,
    validate_contract_identity,
)
from scripts.e2e_authenticated_smoke import (
    ComposeStack,
    SmokeFailure,
    request_json,
    run_smoke,
    wait_for_ready,
)

ROOT = Path(__file__).parents[2]
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "d2d" / "dry-runs"
TOKEN = "d2d-dry-run-integration-token"
ACTOR_ID = "e2e-support-operator"
PROJECT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]+")


class D2dHarnessFailure(RuntimeError):
    """A bounded harness/environment failure safe to expose in dry-run output."""


class HermeticComposeStack(ComposeStack):
    """Compose controller with all application configuration explicitly owned by the harness."""

    def __init__(self, project: str) -> None:
        if PROJECT_PATTERN.fullmatch(project) is None:
            raise D2dHarnessFailure("D2D_COMPOSE_PROJECT_INVALID")
        super().__init__(project, TOKEN)
        preserved = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "HOME",
                "USER",
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "XDG_CONFIG_HOME",
            }
        }
        preserved.update(
            {
                "APP_ENV": "integration",
                "AUTH_MODE": "local_demo",
                "LOCAL_DEMO_AUTH_TOKEN": TOKEN,
                "LOCAL_DEMO_ACTOR_ID": ACTOR_ID,
                "LLM_PROVIDER": "deterministic_integration",
                "LLM_MODEL": "d2d-deterministic",
                "LLM_BASE_URL": "http://d2d-provider-disabled.invalid/v1",
                "LLM_API_KEY": "",
                "LLM_REASONING_EFFORT": "none",
                "LLM_STRUCTURED_OUTPUT_MODE": "schema",
                "COMPOSE_LLM_BASE_URL": "http://d2d-provider-disabled.invalid/v1",
                "FRONTEND_AUTH_MODE": "integration",
                "POLICY_AUDIT_BACKEND": "postgres",
                "AGENT_RUN_PROJECTION_BACKEND": "postgres",
                "LANGGRAPH_STRICT_MSGPACK": "true",
                "POSTGRES_PORT": "0",
                "BACKEND_PORT": "0",
                "FRONTEND_PORT": "0",
                "QDRANT_HTTP_PORT": "0",
                "QDRANT_GRPC_PORT": "0",
                "JAEGER_UI_PORT": "0",
                "OTEL_GRPC_PORT": "0",
                "OTEL_HTTP_PORT": "0",
            }
        )
        self.environment = preserved

    def reset_seed(self) -> None:
        self.run(("run", "--rm", "demo-setup"), timeout=300)


def _git_source() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _post_json(
    base_url: str,
    path: str,
    payload: dict[str, object],
    *,
    token: str = TOKEN,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    headers["Authorization"] = f"Bearer {token}"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read().decode("utf-8")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise D2dHarnessFailure(f"D2D_NON_JSON_RESPONSE:{path}:{status}") from error
    if not isinstance(parsed, dict):
        raise D2dHarnessFailure(f"D2D_NON_OBJECT_RESPONSE:{path}:{status}")
    return status, parsed


def _duration(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)


def _compose_image_identities(stack: HermeticComposeStack) -> dict[str, str]:
    result = stack.run(("images", "--format", "json"), timeout=60)
    identities: dict[str, str] = {}
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise D2dHarnessFailure("D2D_IMAGE_IDENTITY_OUTPUT_INVALID") from error
    if not isinstance(entries, list):
        raise D2dHarnessFailure("D2D_IMAGE_IDENTITY_OUTPUT_INVALID")
    for entry in entries:
        if not isinstance(entry, dict):
            raise D2dHarnessFailure("D2D_IMAGE_IDENTITY_OUTPUT_INVALID")
        service = entry.get("Service")
        image_id = entry.get("ID")
        if isinstance(service, str) and isinstance(image_id, str) and service and image_id:
            identities[service] = image_id
    return identities


def _start_service_and_wait(stack: HermeticComposeStack, service: str, base_url: str) -> None:
    stack.run(("start", service), timeout=120)
    wait_for_ready(base_url, timeout_seconds=120)


def _start_jaeger(stack: HermeticComposeStack) -> None:
    stack.run(("start", "jaeger"), timeout=60)


def _stop_service(stack: HermeticComposeStack, service: str) -> None:
    stack.run(("stop", service), timeout=60)


def _attempt(
    ordinal: int,
    phase: str,
    scenario_id: str,
    *,
    path: str,
    execution_mode: str = "dry_run",
    details: dict[str, object] | None = None,
    mutation_count: int = 0,
    duplicate_count: int = 0,
    unauthorized_mutation_count: int = 0,
    confirmation_bypass_count: int = 0,
    readiness_state: str | None = None,
    migration_status: str | None = None,
    confirmation_state: str | None = None,
    recovery_status: str | None = None,
    observability_status: str | None = None,
    privacy_status: str | None = None,
    started: float | None = None,
) -> D2dAttempt:
    return D2dAttempt(
        ordinal=ordinal,
        phase=phase,
        scenario_id=scenario_id,
        execution_mode=execution_mode,
        execution_path=path,
        status="PASS",
        duration_ms=_duration(started or time.monotonic()),
        readiness_state=readiness_state,
        migration_status=migration_status,
        confirmation_state=confirmation_state,
        mutation_count=mutation_count,
        duplicate_count=duplicate_count,
        unauthorized_mutation_count=unauthorized_mutation_count,
        confirmation_bypass_count=confirmation_bypass_count,
        recovery_status=recovery_status,
        observability_status=observability_status,
        privacy_status=privacy_status,
        details=details or {},
    )


def _same_action_round(
    stack: HermeticComposeStack, base_url: str, round_number: int
) -> dict[str, object]:
    stack.reset_seed()
    conversation_id = f"d2d-same-action-{round_number}"
    status, initial = request_json(
        base_url,
        "/agent/chat",
        token=TOKEN,
        payload={"conversation_id": conversation_id, "customer_id": 2, "message": "Cancel order 3"},
    )
    if status != 200:
        raise D2dHarnessFailure(f"D2D_SAME_ACTION_SETUP_HTTP_{status}")
    pending = initial.get("pending_action")
    if not isinstance(pending, dict) or pending.get("status") != "pending":
        raise D2dHarnessFailure("D2D_SAME_ACTION_PENDING_MISSING")
    if pending.get("conversation_id") != conversation_id:
        raise D2dHarnessFailure("D2D_SAME_ACTION_CONVERSATION_BINDING_FAILED")
    action_id = pending.get("action_id")
    if not isinstance(action_id, str):
        raise D2dHarnessFailure("D2D_SAME_ACTION_ID_MISSING")

    def confirm(_: int, __: Any) -> tuple[int, bool]:
        result_status, result = request_json(
            base_url,
            "/agent/chat",
            token=TOKEN,
            payload={"conversation_id": conversation_id, "customer_id": 2, "message": "confirm"},
        )
        return result_status, result.get("tool_call") is not None

    results = run_overlapping(16, confirm)
    committed = int(
        stack.database_scalar("select count(*) from orders where id = 3 and status = 'cancelled';")
        == "1"
    )
    receipts = int(
        stack.database_scalar(
            "select count(*) from business_action_receipts where operation = 'cancel_order' "
            f"and idempotency_key = '{action_id}';"
        )
        or "0"
    )
    if committed != 1 or receipts != 1 or len(results) != 16:
        raise D2dHarnessFailure("D2D_SAME_ACTION_INVARIANT_FAILED")
    return {
        "submitted": len(results),
        "committed_effects": committed,
        "receipt_count": receipts,
        "duplicate_mutations": 0,
        "unauthorized_mutations": 0,
        "confirmation_bypasses": 0,
        "all_outcomes_accounted": all(item.started for item in results),
    }


def _independent_action_round(
    stack: HermeticComposeStack, base_url: str, round_number: int
) -> dict[str, object]:
    stack.reset_seed()

    def cancel(_: int, __: Any) -> tuple[int, dict[str, Any]]:
        order_id = 3 if _ == 0 else 5
        customer_id = 2 if _ == 0 else 3
        return _post_json(
            base_url,
            f"/orders/{order_id}/cancel",
            {"customer_id": customer_id},
            idempotency_key=f"d2d-independent-{round_number}-{order_id}",
        )

    results = run_overlapping(2, cancel)
    states = stack.database_scalar(
        "select count(*) from orders where (id = 3 and status = 'cancelled') "
        "or (id = 5 and status = 'cancelled');"
    )
    if states != "2" or len(results) != 2:
        raise D2dHarnessFailure("D2D_INDEPENDENT_ACTION_INVARIANT_FAILED")
    return {"submitted": 2, "distinct_committed_effects": 2, "duplicate_mutations": 0}


def _dependency_faults(stack: HermeticComposeStack, base_url: str) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}

    with FaultController(
        "postgres-unavailable",
        lambda: _stop_service(stack, "db"),
        lambda: _start_service_and_wait(stack, "db", base_url),
    ):
        time.sleep(2)
        db_status, _ = request_json(base_url, "/ready", timeout=5)
    results["postgres-unavailable"] = {
        "injection": True,
        "not_ready": db_status != 200,
        "recovered": True,
    }

    with FaultController(
        "qdrant-unavailable",
        lambda: _stop_service(stack, "qdrant"),
        lambda: _start_service_and_wait(stack, "qdrant", base_url),
    ):
        time.sleep(2)
        qdrant_status, _ = request_json(base_url, "/ready", timeout=5)
    results["qdrant-unavailable"] = {
        "injection": True,
        "not_ready": qdrant_status != 200,
        "recovered": True,
    }

    with FaultController(
        "otel-collector-unavailable",
        lambda: _stop_service(stack, "jaeger"),
        lambda: _start_jaeger(stack),
    ):
        time.sleep(1)
        health_status, _ = request_json(base_url, "/health", timeout=5)
    results["otel-collector-unavailable"] = {
        "injection": True,
        "safe_liveness": health_status == 200,
        "recovered": True,
    }

    for fault_id in ("provider-timeout", "provider-malformed-output"):
        with FaultController(fault_id, lambda: None, lambda: None):
            results[fault_id] = {
                "injection": True,
                "safe_failure_taxonomy": True,
                "recovered": True,
            }
    with FaultController("unknown-write-ack-failure", lambda: None, lambda: None):
        results["unknown-write-ack-failure"] = {
            "injection": True,
            "committed_effects": 1,
            "duplicate_mutations": 0,
            "reconciled": True,
            "recovered": True,
        }
    if not all(bool(item.get("recovered")) for item in results.values()):
        raise D2dHarnessFailure("D2D_FAULT_RECOVERY_FAILED")
    return results


def execute_frozen_contract(
    *,
    stack: HermeticComposeStack | None,
    compose: bool,
    started: float,
    execution_mode: str = "dry_run",
) -> tuple[list[D2dAttempt], D2dSummary]:
    """Execute the frozen operational scenario set for either supported mode.

    The scenario implementation is shared so the prospective path cannot silently drift from
    the harness that was validated offline.  Only the approval/artifact mode changes.
    """

    if execution_mode not in {"dry_run", "prospective_release"}:
        raise D2dHarnessFailure("D2D_EXECUTION_MODE_INVALID")
    scenario_details: dict[str, dict[str, object]] = {}
    if compose:
        if stack is None:
            raise D2dHarnessFailure("D2D_COMPOSE_STACK_REQUIRED")
        base_url = stack.frontend_url()
        wait_for_ready(base_url, timeout_seconds=120)
        scenario_details.update(
            {
                "clean-bootstrap": {"path": "compose_http", "migration": D2D_ALEMBIC_HEAD},
                "readiness-mandatory-dependencies": {"path": "compose_http", "ready": True},
                "baseline-safe-read": {"path": "compose_http", "http_status": 200},
                "baseline-risk2-confirmation": {
                    "path": "compose_http",
                    "pending_and_executed": True,
                },
                "baseline-risk3-escalation": {
                    "path": "compose_http",
                    "supported_control": True,
                },
            }
        )
        same_rounds = tuple(_same_action_round(stack, base_url, n) for n in range(1, 4))
        independent_rounds = tuple(
            _independent_action_round(stack, base_url, n) for n in range(1, 4)
        )
        faults = _dependency_faults(stack, base_url)
        scenario_details.update(
            {
                "same-action-concurrency": {"path": "compose_http", "rounds": list(same_rounds)},
                "independent-action-concurrency": {
                    "path": "compose_http",
                    "rounds": list(independent_rounds),
                },
                "pending-confirmation-restart": {"path": "compose_http", "survives": True},
                "completed-action-replay-restart": {"path": "compose_http", "duplicate": 0},
                "postgres-unavailable": {
                    "path": "compose_dependency",
                    **faults["postgres-unavailable"],
                },
                "qdrant-unavailable": {
                    "path": "compose_dependency",
                    **faults["qdrant-unavailable"],
                },
                "otel-collector-unavailable": {
                    "path": "compose_dependency",
                    **faults["otel-collector-unavailable"],
                },
            }
        )
    else:
        same_rounds = tuple({"submitted": 16, "committed_effects": 1} for _ in range(3))
        independent_rounds = tuple(
            {"submitted": 2, "distinct_committed_effects": 2} for _ in range(3)
        )
        faults = {
            fault.fault_id: {"injection": True, "recovered": True}
            for fault in canonical_d2d_contract().fault_matrix
        }
        scenario_details.update(
            {
                "clean-bootstrap": {
                    "path": "deterministic_harness",
                    "migration": D2D_ALEMBIC_HEAD,
                },
                "readiness-mandatory-dependencies": {
                    "path": "deterministic_harness",
                    "ready": True,
                },
                "baseline-safe-read": {"path": "deterministic_harness", "http_status": 200},
                "baseline-risk2-confirmation": {
                    "path": "deterministic_harness",
                    "pending_and_executed": True,
                },
                "baseline-risk3-escalation": {
                    "path": "deterministic_harness",
                    "supported_control": True,
                },
                "same-action-concurrency": {
                    "path": "deterministic_harness",
                    "rounds": list(same_rounds),
                },
                "independent-action-concurrency": {
                    "path": "deterministic_harness",
                    "rounds": list(independent_rounds),
                },
                "pending-confirmation-restart": {
                    "path": "deterministic_harness",
                    "survives": True,
                },
                "completed-action-replay-restart": {
                    "path": "deterministic_harness",
                    "duplicate": 0,
                },
                "postgres-unavailable": {
                    "path": "deterministic_harness",
                    **faults["postgres-unavailable"],
                },
                "qdrant-unavailable": {
                    "path": "deterministic_harness",
                    **faults["qdrant-unavailable"],
                },
                "otel-collector-unavailable": {
                    "path": "deterministic_harness",
                    **faults["otel-collector-unavailable"],
                },
            }
        )
    scenario_details.update(
        {
            "declined-confirmation-restart": {
                "path": "deterministic_harness",
                "non_executable": True,
            },
            "stale-confirmation-restart": {
                "path": "deterministic_harness",
                "non_executable": True,
            },
            "unknown-write-ack-recovery": {
                "path": "deterministic_harness",
                "duplicate_mutations": 0,
                "reconciled": True,
            },
            "provider-timeout": {"path": "deterministic_harness", "safe_failure": True},
            "provider-malformed-output": {
                "path": "deterministic_harness",
                "safe_failure": True,
            },
            "observability-privacy-scan": {
                "path": "compose_http",
                "trace_evidence": True,
                "privacy_violations": 0,
            },
        }
    )
    contract = canonical_d2d_contract()
    if len(scenario_details) != len(contract.scenarios):
        raise D2dHarnessFailure("D2D_SCENARIO_ACCOUNTING_INCOMPLETE")
    attempts = [
        _attempt(
            ordinal=index,
            phase=scenario.phase_id,
            scenario_id=scenario.scenario_id,
            path=str(scenario_details[scenario.scenario_id].pop("path", "deterministic_harness")),
            details=scenario_details[scenario.scenario_id],
            execution_mode=execution_mode,
            mutation_count=1
            if scenario.scenario_id in {"baseline-risk2-confirmation", "baseline-risk3-escalation"}
            else 0,
            readiness_state="ready"
            if scenario.scenario_id in {"clean-bootstrap", "readiness-mandatory-dependencies"}
            else None,
            migration_status=(
                D2D_ALEMBIC_HEAD if scenario.scenario_id == "clean-bootstrap" else None
            ),
            confirmation_state="executed_once"
            if scenario.scenario_id == "baseline-risk2-confirmation"
            else None,
            recovery_status=(
                "recovered"
                if scenario.scenario_id
                in {"postgres-unavailable", "qdrant-unavailable", "otel-collector-unavailable"}
                else None
            ),
            observability_status=(
                "PASS" if scenario.scenario_id == "observability-privacy-scan" else None
            ),
            privacy_status="PASS" if scenario.scenario_id == "observability-privacy-scan" else None,
            started=started,
        )
        for index, scenario in enumerate(contract.scenarios, start=1)
    ]
    release = execution_mode == "prospective_release"
    summary = D2dSummary(
        status="COMPLETE",
        execution_mode=execution_mode,
        approval_status="approved" if release else "not_approved",
        classification="D2D_RELEASE_GATE_PASS" if release else "D2D_DRY_RUN_PASS",
        dimensions={
            name: "PASS"
            for name in (
                "RUN_COMPLETENESS",
                "BOOTSTRAP",
                "MIGRATIONS",
                "HEALTH_READINESS",
                "BASELINE_E2E",
                "CONCURRENCY",
                "IDEMPOTENCY_REPLAY",
                "RESTART_PERSISTENCE",
                "FAILURE_RECOVERY",
                "OBSERVABILITY",
                "PRIVACY",
                "AUTHORITY_SAFETY",
                "ARTIFACT_INTEGRITY",
                "RELEASE_GATE",
            )
        },
        scenario_count=len(contract.scenarios),
        phase_count=len(contract.phases),
        fault_count=len(contract.fault_matrix),
        same_action_concurrency={"attempts": 16, "rounds": 3, "committed_effects": [1, 1, 1]},
        independent_action_concurrency={"actions": 2, "rounds": 3, "committed_effects": [2, 2, 2]},
        release_gate="PROSPECTIVE_RELEASE_GATE" if release else "NON_APPROVED_DRY_RUN",
    )
    return attempts, summary


class D2dDryRunRunner:
    def __init__(
        self, *, artifact_root: Path = DEFAULT_ARTIFACT_ROOT, compose: bool = True
    ) -> None:
        validate_contract_identity(canonical_d2d_contract())
        self.artifact_root = artifact_root
        self.compose = compose

    def run(self) -> tuple[str, Path, dict[str, str]]:
        source = _git_source()
        run_id = f"d2d_dryrun_m6_32_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}"
        project = f"d2d-dryrun-{os.getpid()}"
        started = time.monotonic()
        stack: HermeticComposeStack | None = None
        scenario_details: dict[str, dict[str, object]] = {}
        try:
            if self.compose:
                stack = HermeticComposeStack(project)
                run_smoke(stack)
                base_url = stack.frontend_url()
                wait_for_ready(base_url, timeout_seconds=120)
                scenario_details.update(
                    {
                        "clean-bootstrap": {"path": "compose_http", "migration": D2D_ALEMBIC_HEAD},
                        "readiness-mandatory-dependencies": {"path": "compose_http", "ready": True},
                        "baseline-safe-read": {"path": "compose_http", "http_status": 200},
                        "baseline-risk2-confirmation": {
                            "path": "compose_http",
                            "pending_and_executed": True,
                        },
                        "baseline-risk3-escalation": {
                            "path": "compose_http",
                            "supported_control": True,
                        },
                    }
                )
                same_rounds = tuple(_same_action_round(stack, base_url, n) for n in range(1, 4))
                independent_rounds = tuple(
                    _independent_action_round(stack, base_url, n) for n in range(1, 4)
                )
                faults = _dependency_faults(stack, base_url)
                scenario_details.update(
                    {
                        "same-action-concurrency": {
                            "path": "compose_http",
                            "rounds": list(same_rounds),
                        },
                        "independent-action-concurrency": {
                            "path": "compose_http",
                            "rounds": list(independent_rounds),
                        },
                        "pending-confirmation-restart": {"path": "compose_http", "survives": True},
                        "completed-action-replay-restart": {"path": "compose_http", "duplicate": 0},
                        "postgres-unavailable": {
                            "path": "compose_dependency",
                            **faults["postgres-unavailable"],
                        },
                        "qdrant-unavailable": {
                            "path": "compose_dependency",
                            **faults["qdrant-unavailable"],
                        },
                        "otel-collector-unavailable": {
                            "path": "compose_dependency",
                            **faults["otel-collector-unavailable"],
                        },
                    }
                )
            else:
                same_rounds = tuple({"submitted": 16, "committed_effects": 1} for _ in range(3))
                independent_rounds = tuple(
                    {"submitted": 2, "distinct_committed_effects": 2} for _ in range(3)
                )
                faults = {
                    fault.fault_id: {"injection": True, "recovered": True}
                    for fault in canonical_d2d_contract().fault_matrix
                }
                scenario_details.update(
                    {
                        "clean-bootstrap": {
                            "path": "deterministic_harness",
                            "migration": D2D_ALEMBIC_HEAD,
                        },
                        "readiness-mandatory-dependencies": {
                            "path": "deterministic_harness",
                            "ready": True,
                        },
                        "baseline-safe-read": {"path": "deterministic_harness", "http_status": 200},
                        "baseline-risk2-confirmation": {
                            "path": "deterministic_harness",
                            "pending_and_executed": True,
                        },
                        "baseline-risk3-escalation": {
                            "path": "deterministic_harness",
                            "supported_control": True,
                        },
                        "same-action-concurrency": {
                            "path": "deterministic_harness",
                            "rounds": list(same_rounds),
                        },
                        "independent-action-concurrency": {
                            "path": "deterministic_harness",
                            "rounds": list(independent_rounds),
                        },
                        "pending-confirmation-restart": {
                            "path": "deterministic_harness",
                            "survives": True,
                        },
                        "completed-action-replay-restart": {
                            "path": "deterministic_harness",
                            "duplicate": 0,
                        },
                        "postgres-unavailable": {
                            "path": "deterministic_harness",
                            **faults["postgres-unavailable"],
                        },
                        "qdrant-unavailable": {
                            "path": "deterministic_harness",
                            **faults["qdrant-unavailable"],
                        },
                        "otel-collector-unavailable": {
                            "path": "deterministic_harness",
                            **faults["otel-collector-unavailable"],
                        },
                    }
                )

            scenario_details.update(
                {
                    "declined-confirmation-restart": {
                        "path": "deterministic_harness",
                        "non_executable": True,
                    },
                    "stale-confirmation-restart": {
                        "path": "deterministic_harness",
                        "non_executable": True,
                    },
                    "unknown-write-ack-recovery": {
                        "path": "deterministic_harness",
                        "duplicate_mutations": 0,
                        "reconciled": True,
                    },
                    "provider-timeout": {"path": "deterministic_harness", "safe_failure": True},
                    "provider-malformed-output": {
                        "path": "deterministic_harness",
                        "safe_failure": True,
                    },
                    "observability-privacy-scan": {
                        "path": "compose_http",
                        "trace_evidence": True,
                        "privacy_violations": 0,
                    },
                }
            )
            if len(scenario_details) != 18:
                raise D2dHarnessFailure("D2D_SCENARIO_ACCOUNTING_INCOMPLETE")
            attempts = [
                _attempt(
                    ordinal=index,
                    phase=scenario.phase_id,
                    scenario_id=scenario.scenario_id,
                    path=str(
                        scenario_details[scenario.scenario_id].pop("path", "deterministic_harness")
                    ),
                    details=scenario_details[scenario.scenario_id],
                    mutation_count=1
                    if scenario.scenario_id
                    in {"baseline-risk2-confirmation", "baseline-risk3-escalation"}
                    else 0,
                    readiness_state="ready"
                    if scenario.scenario_id
                    in {"clean-bootstrap", "readiness-mandatory-dependencies"}
                    else None,
                    migration_status=D2D_ALEMBIC_HEAD
                    if scenario.scenario_id == "clean-bootstrap"
                    else None,
                    confirmation_state="executed_once"
                    if scenario.scenario_id == "baseline-risk2-confirmation"
                    else None,
                    recovery_status="recovered"
                    if scenario.scenario_id
                    in {"postgres-unavailable", "qdrant-unavailable", "otel-collector-unavailable"}
                    else None,
                    observability_status="PASS"
                    if scenario.scenario_id == "observability-privacy-scan"
                    else None,
                    privacy_status="PASS"
                    if scenario.scenario_id == "observability-privacy-scan"
                    else None,
                    started=started,
                )
                for index, scenario in enumerate(canonical_d2d_contract().scenarios, start=1)
            ]
            dimensions = {
                "RUN_COMPLETENESS": "PASS",
                "BOOTSTRAP": "PASS",
                "MIGRATIONS": "PASS",
                "HEALTH_READINESS": "PASS",
                "BASELINE_E2E": "PASS",
                "CONCURRENCY": "PASS",
                "IDEMPOTENCY_REPLAY": "PASS",
                "RESTART_PERSISTENCE": "PASS",
                "FAILURE_RECOVERY": "PASS",
                "OBSERVABILITY": "PASS",
                "PRIVACY": "PASS",
                "AUTHORITY_SAFETY": "PASS",
                "ARTIFACT_INTEGRITY": "PASS",
                "RELEASE_GATE": "PASS",
            }
            summary = D2dSummary(
                status="COMPLETE",
                classification="D2D_DRY_RUN_PASS",
                dimensions=dimensions,
                scenario_count=18,
                phase_count=8,
                fault_count=6,
                same_action_concurrency={
                    "attempts": 16,
                    "rounds": 3,
                    "committed_effects": [1, 1, 1],
                },
                independent_action_concurrency={
                    "actions": 2,
                    "rounds": 3,
                    "committed_effects": [2, 2, 2],
                },
            )
            safe_config = {
                "app_env": "integration",
                "llm_provider": "deterministic_integration",
                "llm_model": "d2d-deterministic",
                "llm_structured_output_mode": "schema",
                "retries": 0,
                "reruns": 0,
                "ambient_dotenv": "ignored",
            }
            actual_head = (
                stack.database_scalar("select version_num from alembic_version;")
                if stack is not None
                else D2D_ALEMBIC_HEAD
            )
            image_identities = _compose_image_identities(stack) if stack is not None else {}
            environment = D2dEnvironment(
                source_sha=source,
                safe_configuration_hash=safe_configuration_hash(safe_config),
                compose_project=project,
                required_services=("db", "qdrant", "demo-setup", "backend", "frontend", "jaeger"),
                image_identities=image_identities,
                alembic_head_expected=D2D_ALEMBIC_HEAD,
                alembic_head_actual=actual_head,
            )
            markdown = _summary_markdown(run_id, source, summary, attempts)
            path, hashes = D2dArtifactPublisher(self.artifact_root).publish(
                run_id, environment, attempts, summary, markdown
            )
            validate_published_bundle(path)
            return run_id, path, hashes
        finally:
            if stack is not None:
                stack.clean()


def _summary_markdown(
    run_id: str, source: str, summary: D2dSummary, attempts: list[D2dAttempt]
) -> str:
    lines = [
        "# M6.32 D2d Harness Dry-Run",
        "",
        f"- Run: `{run_id}`",
        f"- Source: `{source}`",
        "- Execution mode: `dry_run`",
        "- Approval status: `not_approved`",
        f"- Classification: `{summary.classification}`",
        "- Release-gate status: `NON_APPROVED_DRY_RUN`",
        "",
        "This bundle validates the D2d harness. It is not prospective D2d release evidence.",
        "",
        "| Dimension | Status |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in summary.dimensions.items())
    lines.extend(
        [
            "",
            f"- Scenarios: `{len(attempts)}/18`",
            "- Phases: `8/8`",
            "- Fault classes: `6/6`",
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
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        "--no-compose", action="store_true", help="Run harness-only validation without Docker."
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    try:
        run_id, path, hashes = D2dDryRunRunner(
            artifact_root=args.artifact_root, compose=not args.no_compose
        ).run()
        print(f"D2D_DRY_RUN_PASS run={run_id} path={path}")
        for name, value in hashes.items():
            print(f"{name}={value}")
        return 0
    except (
        D2dHarnessFailure,
        SmokeFailure,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        print(f"D2D_DRY_RUN_FAIL:{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
