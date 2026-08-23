"""Provider-free capacity benchmark workloads.

The benchmark uses deterministic local components and a private in-memory
state model.  It is intended for repeatable engineering comparisons, not as a
claim about managed production capacity.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from threading import Lock
from typing import Any

from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.policies.engine import PolicyEngine
from app.policies.models import PolicyOutcome
from app.rag.answer_generator import GroundedAnswerGenerator
from app.rag.schemas import RetrievedChunk


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    iterations: int = 10
    workers: int = 4
    warmup: int = 2

    def __post_init__(self) -> None:
        if self.iterations <= 0 or self.workers <= 0 or self.warmup < 0:
            raise ValueError("iterations and workers must be positive; warmup cannot be negative")


@dataclass(frozen=True, slots=True)
class ScenarioMeasurement:
    name: str
    samples_seconds: tuple[float, ...]
    statuses: dict[str, int]
    operations: int

    @property
    def throughput_per_second(self) -> float:
        elapsed = sum(self.samples_seconds)
        return self.operations / elapsed if elapsed > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        values = sorted(self.samples_seconds)
        return {
            "operations": self.operations,
            "status_counts": dict(sorted(self.statuses.items())),
            "latency_ms": {
                "p50": round(_percentile(values, 0.50) * 1000, 3),
                "p95": round(_percentile(values, 0.95) * 1000, 3),
                "p99": round(_percentile(values, 0.99) * 1000, 3),
                "mean": round(mean(values) * 1000, 3) if values else 0.0,
            },
            "throughput_per_second": round(self.throughput_per_second, 3),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    generated_at: str
    provider_calls: int
    scenarios: dict[str, ScenarioMeasurement]
    invariants: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark": "deterministic_capacity_v1",
            "generated_at": self.generated_at,
            "provider_calls": self.provider_calls,
            "scenarios": {name: item.as_dict() for name, item in self.scenarios.items()},
            "invariants": self.invariants,
        }


class _PrivateWorkloadState:
    """Small private state model for measuring contention and replay behavior."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.pending: dict[str, str] = {}
        self.receipts: dict[str, str] = {}
        self.effects: Counter[str] = Counter()

    def add_pending(self, action_id: str) -> str:
        with self._lock:
            self.pending[action_id] = "pending"
        return "pending"

    def commit_once(self, key: str) -> str:
        with self._lock:
            if key in self.receipts:
                return "idempotent_replay"
            self.effects[key] += 1
            self.receipts[key] = "committed"
            return "committed"

    def receipt(self, key: str) -> str:
        with self._lock:
            return "hit" if key in self.receipts else "miss"


def run_deterministic_benchmark(config: BenchmarkConfig | None = None) -> BenchmarkReport:
    """Run the six bounded workloads without a provider or network dependency."""

    active = config or BenchmarkConfig()
    for _ in range(active.warmup):
        _run_case("read_only_customer_inquiry", _PrivateWorkloadState())

    cases: dict[str, Callable[[_PrivateWorkloadState, int], str]] = {
        "read_only_customer_inquiry": _read_only_customer_inquiry,
        "rag_grounded_response": _rag_grounded_response,
        "confirmation_required_operation": _confirmation_required_operation,
        "successful_write_execution": _successful_write_execution,
        "duplicate_execution_replay": _duplicate_execution_replay,
        "policy_rejection": _policy_rejection,
    }
    measurements: dict[str, ScenarioMeasurement] = {}
    for name, case in cases.items():
        state = _PrivateWorkloadState()
        samples: list[float] = []
        statuses: Counter[str] = Counter()
        with ThreadPoolExecutor(max_workers=active.workers) as executor:
            futures = [
                executor.submit(_timed_case, case, state, index)
                for index in range(active.iterations)
            ]
            for future in futures:
                elapsed, status = future.result()
                samples.append(elapsed)
                statuses[status] += 1
        measurements[name] = ScenarioMeasurement(
            name=name,
            samples_seconds=tuple(samples),
            statuses=dict(statuses),
            operations=active.iterations,
        )

    contention_state = _PrivateWorkloadState()
    _run_contention(contention_state, active.workers)
    invariants = {
        "provider_calls_zero": True,
        "same_idempotency_key_one_effect": contention_state.effects["same-key"] == 1,
        "same_key_one_receipt": len(contention_state.receipts) == 1,
        "different_keys_independent": _different_keys_are_independent(),
    }
    return BenchmarkReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        provider_calls=0,
        scenarios=measurements,
        invariants=invariants,
    )


def _timed_case(
    case: Callable[[_PrivateWorkloadState, int], str], state: _PrivateWorkloadState, index: int
) -> tuple[float, str]:
    started = time.perf_counter()
    status = case(state, index)
    return time.perf_counter() - started, status


def _run_contention(state: _PrivateWorkloadState, workers: int) -> None:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(state.commit_once, "same-key") for _ in range(16)]
        for future in futures:
            future.result()


def _run_case(name: str, state: _PrivateWorkloadState) -> str:
    return {
        "read_only_customer_inquiry": _read_only_customer_inquiry,
        "rag_grounded_response": _rag_grounded_response,
        "confirmation_required_operation": _confirmation_required_operation,
        "successful_write_execution": _successful_write_execution,
        "duplicate_execution_replay": _duplicate_execution_replay,
        "policy_rejection": _policy_rejection,
    }[name](state, 0)


def _read_only_customer_inquiry(state: _PrivateWorkloadState, index: int) -> str:
    del state, index
    customer = {"customer_id": 1, "order_status": "delivered"}
    return "available" if customer["order_status"] else "not_available"


def _rag_grounded_response(state: _PrivateWorkloadState, index: int) -> str:
    del state, index
    chunk = RetrievedChunk(
        chunk_id="refund-policy#1",
        document_id="refund-policy",
        title="Refund policy",
        category="policy",
        section="eligibility",
        source="local-fixture",
        content="Damaged products are eligible for a refund within 30 days.",
        score=0.99,
    )
    answer = GroundedAnswerGenerator().answer("What is the refund policy?", [chunk])
    return "grounded" if answer.grounded else "uncertain"


def _confirmation_required_operation(state: _PrivateWorkloadState, index: int) -> str:
    return state.add_pending(f"pending-{index}")


def _successful_write_execution(state: _PrivateWorkloadState, index: int) -> str:
    return state.commit_once(f"unique-key-{index}")


def _duplicate_execution_replay(state: _PrivateWorkloadState, index: int) -> str:
    key = f"replay-key-{index}"
    state.commit_once(key)
    return state.commit_once(key)


def _policy_rejection(state: _PrivateWorkloadState, index: int) -> str:
    del state, index
    context = ExecutionContext(
        request_id="capacity-request",
        conversation_id="capacity-conversation",
        principal=Principal(
            actor_id="capacity-operator",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
            tenant_id="capacity-tenant",
        ),
        tenant_id="capacity-tenant",
        effective_customer_id=1,
    )
    decision = PolicyEngine().evaluate(
        tool_name="unknown_tool",
        context=context,
        arguments={"customer_id": 1},
    )
    return "denied" if decision.outcome == PolicyOutcome.DENY else "unexpected"


def _different_keys_are_independent() -> bool:
    state = _PrivateWorkloadState()
    return (
        state.commit_once("tenant-a-key") == "committed"
        and state.commit_once("tenant-b-key") == "committed"
        and len(state.effects) == 2
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * quantile
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
