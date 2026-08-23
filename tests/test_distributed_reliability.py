from __future__ import annotations

import threading
from datetime import UTC, datetime

import httpx
import pytest

from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.resilience.config import ResilienceConfig
from app.resilience.control import CircuitState, ReliabilityController
from app.resilience.errors import (
    BulkheadRejectedError,
    CircuitOpenError,
    RateLimitExceededError,
    RetryBudgetExhaustedError,
    RetryExhaustedError,
    UnknownWriteOutcomeError,
)
from app.resilience.retry import run_with_retry


def _config(**overrides: object) -> ResilienceConfig:
    values: dict[str, object] = {
        "max_retries": 2,
        "initial_backoff_ms": 100,
        "max_backoff_ms": 1000,
        "jitter_ratio": 0.2,
        "retry_budget_attempts": 100,
        "circuit_failure_threshold": 5,
        "bulkhead_default_limit": 4,
        "bulkhead_provider_limit": 2,
        "principal_rate_limit": 10,
        "customer_rate_limit": 10,
        "provider_rate_limit": 10,
    }
    values.update(overrides)
    return ResilienceConfig(**values)  # type: ignore[arg-type]


def _context(actor_id: str, customer_id: int) -> ExecutionContext:
    return ExecutionContext(
        request_id=f"request-{actor_id}-{customer_id}",
        conversation_id=f"conversation-{actor_id}-{customer_id}",
        principal=Principal(
            actor_id=actor_id,
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=customer_id,
    )


def test_transient_failure_uses_exponential_backoff_with_jitter() -> None:
    calls = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("bounded transient failure")
        return "ok"

    assert (
        run_with_retry(
            operation,
            dependency="retrieval",
            config=_config(),
            sleeper=sleeps.append,
            random_source=lambda: 0.75,
        )
        == "ok"
    )
    assert calls == 3
    assert sleeps == pytest.approx([0.11, 0.22])


def test_retry_after_header_is_honored_within_deadline() -> None:
    calls = 0
    sleeps: list[float] = []
    request = httpx.Request("GET", "https://dependency.example/status")
    response = httpx.Response(503, headers={"Retry-After": "2"}, request=request)

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.HTTPStatusError("unavailable", request=request, response=response)
        return "ok"

    assert (
        run_with_retry(
            operation,
            dependency="retrieval",
            config=_config(max_retries=1),
            timeout_seconds=5,
            sleeper=sleeps.append,
            random_source=lambda: 0.5,
            wall_clock=lambda: datetime(2026, 8, 24, tzinfo=UTC),
        )
        == "ok"
    )
    assert sleeps == [2.0]


def test_deadline_prevents_a_retry_that_cannot_start_safely() -> None:
    now = 10.0
    calls = 0

    def clock() -> float:
        return now

    def operation() -> None:
        nonlocal calls, now
        calls += 1
        now += 0.08
        raise TimeoutError("transient")

    def sleeper(delay: float) -> None:
        nonlocal now
        now += delay

    with pytest.raises(RetryExhaustedError):
        run_with_retry(
            operation,
            dependency="retrieval",
            config=_config(max_retries=2, jitter_ratio=0.0),
            deadline=10.1,
            clock=clock,
            sleeper=sleeper,
        )
    assert calls == 1


def test_unknown_write_outcome_is_never_retried_with_controller() -> None:
    calls = 0
    controller = ReliabilityController(_config())

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise UnknownWriteOutcomeError("refund.create")

    with pytest.raises(UnknownWriteOutcomeError):
        run_with_retry(
            operation,
            dependency="tool",
            operation_type="write",
            config=_config(),
            controller=controller,
            service_identity="tool:refund.create",
        )
    assert calls == 1


def test_retry_budget_stops_retry_storm() -> None:
    calls = 0
    config = _config(max_retries=3, retry_budget_attempts=1)
    controller = ReliabilityController(config)

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("transient")

    with pytest.raises(RetryBudgetExhaustedError):
        run_with_retry(
            operation,
            dependency="retrieval",
            config=config,
            controller=controller,
            sleeper=lambda _: None,
        )
    assert calls == 2


def test_circuit_opens_and_rejects_without_calling_dependency() -> None:
    now = 0.0
    calls = 0
    config = _config(max_retries=0, circuit_failure_threshold=2)
    controller = ReliabilityController(config, clock=lambda: now)

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("down")

    for _ in range(2):
        with pytest.raises(RetryExhaustedError):
            run_with_retry(
                operation,
                dependency="retrieval",
                config=config,
                controller=controller,
            )
    with pytest.raises(CircuitOpenError):
        run_with_retry(
            operation,
            dependency="retrieval",
            config=config,
            controller=controller,
        )
    assert calls == 2
    snapshot = controller.circuit_snapshot("retrieval")
    assert snapshot.service_identity == "retrieval"
    assert snapshot.state == CircuitState.OPEN
    assert snapshot.failure_count == 2


def test_half_open_probe_recovers_circuit() -> None:
    now = 0.0
    config = _config(
        max_retries=0,
        circuit_failure_threshold=1,
        circuit_recovery_seconds=5,
        circuit_half_open_attempts=1,
    )
    controller = ReliabilityController(config, clock=lambda: now)

    with pytest.raises(RetryExhaustedError):
        run_with_retry(
            lambda: (_ for _ in ()).throw(TimeoutError("down")),
            dependency="retrieval",
            config=config,
            controller=controller,
        )
    now = 6.0
    assert (
        run_with_retry(
            lambda: "healthy",
            dependency="retrieval",
            config=config,
            controller=controller,
        )
        == "healthy"
    )
    assert controller.circuit_state("retrieval") == CircuitState.CLOSED
    assert controller.circuit_snapshot("retrieval").recovery_attempts == 1


def test_bulkhead_rejects_concurrent_pressure_without_exhausting_other_service() -> None:
    config = _config(
        max_retries=0,
        bulkhead_default_limit=1,
        bulkhead_wait_seconds=0,
    )
    controller = ReliabilityController(config)
    entered = threading.Event()
    release = threading.Event()
    finished: list[str] = []

    def slow_operation() -> str:
        entered.set()
        assert release.wait(timeout=2)
        return "slow-ok"

    def worker() -> None:
        finished.append(
            run_with_retry(
                slow_operation,
                dependency="retrieval",
                config=config,
                controller=controller,
                service_identity="retrieval:qdrant",
            )
        )

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=2)
    with pytest.raises(BulkheadRejectedError):
        run_with_retry(
            lambda: "must-not-run",
            dependency="retrieval",
            config=config,
            controller=controller,
            service_identity="retrieval:qdrant",
        )
    assert (
        run_with_retry(
            lambda: "memory-ok",
            dependency="memory",
            config=config,
            controller=controller,
            service_identity="memory:postgres",
        )
        == "memory-ok"
    )
    release.set()
    thread.join(timeout=2)
    assert finished == ["slow-ok"]


def test_principal_and_customer_rate_limits_are_isolated() -> None:
    config = _config(principal_rate_limit=1, customer_rate_limit=1)
    controller = ReliabilityController(config)
    controller.enforce_request_limits(_context("operator-a", 1))
    with pytest.raises(RateLimitExceededError) as principal_limit:
        controller.enforce_request_limits(_context("operator-a", 1))
    assert principal_limit.value.scope == "principal"

    controller.enforce_request_limits(_context("operator-b", 2))
    with pytest.raises(RateLimitExceededError) as customer_limit:
        controller.enforce_request_limits(_context("operator-c", 2))
    assert customer_limit.value.scope == "customer"


def test_provider_rate_limit_isolated_from_other_dependency() -> None:
    config = _config(max_retries=0, provider_rate_limit=1)
    controller = ReliabilityController(config)
    assert (
        run_with_retry(
            lambda: "first",
            dependency="llm",
            config=config,
            controller=controller,
            service_identity="llm:provider-a",
            provider_rate_limit=True,
        )
        == "first"
    )
    with pytest.raises(RateLimitExceededError):
        run_with_retry(
            lambda: "second",
            dependency="llm",
            config=config,
            controller=controller,
            service_identity="llm:provider-a",
            provider_rate_limit=True,
        )
    assert (
        run_with_retry(
            lambda: "retrieval",
            dependency="retrieval",
            config=config,
            controller=controller,
            service_identity="retrieval:qdrant",
        )
        == "retrieval"
    )
