"""Thread-safe, bounded reliability controls for one application replica."""

from __future__ import annotations

import hashlib
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from app.core.context import ExecutionContext
from app.observability.metrics import get_metrics, record_circuit_open_summary
from app.resilience.config import ResilienceConfig
from app.resilience.errors import (
    BulkheadRejectedError,
    CircuitOpenError,
    RateLimitExceededError,
)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class _CircuitRecord:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at: float = 0.0
    half_open_in_flight: int = 0
    recovery_attempts: int = 0


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    service_identity: str
    state: CircuitState
    failure_count: int
    recovery_attempts: int


class ReliabilityController:
    """Own per-replica circuit, retry-budget, bulkhead, and rate-limit state."""

    def __init__(
        self,
        config: ResilienceConfig,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.config = config
        self._clock = clock
        self._lock = threading.RLock()
        self._circuits: dict[str, _CircuitRecord] = defaultdict(_CircuitRecord)
        self._bulkheads: dict[str, threading.BoundedSemaphore] = {}
        self._retry_attempts: dict[str, deque[float]] = defaultdict(deque)
        self._rate_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def enforce_request_limits(self, context: ExecutionContext) -> None:
        self._consume_rate_limit(
            "principal",
            context.principal.actor_id,
            self.config.principal_rate_limit,
        )
        try:
            self._consume_rate_limit(
                "customer",
                str(context.effective_customer_id),
                self.config.customer_rate_limit,
            )
        except RateLimitExceededError:
            self._rollback_rate_limit("principal", context.principal.actor_id)
            raise

    def enforce_provider_limit(self, provider_identity: str) -> None:
        self._consume_rate_limit("provider", provider_identity, self.config.provider_rate_limit)

    def consume_retry_budget(self, service_identity: str) -> bool:
        now = self._clock()
        with self._lock:
            events = self._retry_attempts[service_identity]
            _expire(events, now - self.config.retry_budget_window_seconds)
            if len(events) >= self.config.retry_budget_attempts:
                return False
            events.append(now)
            return True

    def before_call(self, service_identity: str) -> None:
        now = self._clock()
        with self._lock:
            circuit = self._circuits[service_identity]
            if circuit.state == CircuitState.OPEN:
                if now - circuit.opened_at < self.config.circuit_recovery_seconds:
                    get_metrics().circuit_open.add(1, {"service": service_identity})
                    raise CircuitOpenError(service_identity)
                circuit.state = CircuitState.HALF_OPEN
                circuit.half_open_in_flight = 0
            if circuit.state == CircuitState.HALF_OPEN:
                if circuit.half_open_in_flight >= self.config.circuit_half_open_attempts:
                    get_metrics().circuit_open.add(1, {"service": service_identity})
                    raise CircuitOpenError(service_identity)
                circuit.half_open_in_flight += 1
                circuit.recovery_attempts += 1

    def record_success(self, service_identity: str) -> None:
        with self._lock:
            circuit = self._circuits[service_identity]
            recovered = circuit.state == CircuitState.HALF_OPEN
            circuit.state = CircuitState.CLOSED
            circuit.failure_count = 0
            circuit.half_open_in_flight = 0
            if recovered:
                get_metrics().circuit_recovered.add(1, {"service": service_identity})

    def cancel_call(self, service_identity: str) -> None:
        """Release a half-open probe reservation when no dependency call was made."""

        with self._lock:
            circuit = self._circuits[service_identity]
            if circuit.state == CircuitState.HALF_OPEN and circuit.half_open_in_flight > 0:
                circuit.half_open_in_flight -= 1

    def record_failure(self, service_identity: str) -> None:
        now = self._clock()
        with self._lock:
            circuit = self._circuits[service_identity]
            if circuit.state == CircuitState.HALF_OPEN:
                self._open_circuit(circuit, service_identity, now)
                return
            circuit.failure_count += 1
            if circuit.failure_count >= self.config.circuit_failure_threshold:
                self._open_circuit(circuit, service_identity, now)

    def circuit_state(self, service_identity: str) -> CircuitState:
        with self._lock:
            return self._circuits[service_identity].state

    def circuit_snapshot(self, service_identity: str) -> CircuitSnapshot:
        with self._lock:
            circuit = self._circuits[service_identity]
            return CircuitSnapshot(
                service_identity=service_identity,
                state=circuit.state,
                failure_count=circuit.failure_count,
                recovery_attempts=circuit.recovery_attempts,
            )

    @contextmanager
    def bulkhead(self, service_identity: str, dependency: str) -> Iterator[None]:
        semaphore = self._bulkhead(service_identity, dependency)
        acquired = semaphore.acquire(timeout=self.config.bulkhead_wait_seconds)
        if not acquired:
            raise BulkheadRejectedError(service_identity)
        try:
            yield
        finally:
            semaphore.release()

    def _bulkhead(self, service_identity: str, dependency: str) -> threading.BoundedSemaphore:
        with self._lock:
            semaphore = self._bulkheads.get(service_identity)
            if semaphore is None:
                capacity = (
                    self.config.bulkhead_provider_limit
                    if dependency == "llm"
                    else self.config.bulkhead_default_limit
                )
                semaphore = threading.BoundedSemaphore(capacity)
                self._bulkheads[service_identity] = semaphore
            return semaphore

    def _consume_rate_limit(self, scope: str, raw_key: str, limit: int) -> None:
        key = (scope, _bounded_identity(raw_key))
        now = self._clock()
        with self._lock:
            events = self._rate_events[key]
            _expire(events, now - self.config.rate_limit_window_seconds)
            if len(events) >= limit:
                retry_after = self.config.rate_limit_window_seconds - (now - events[0])
                get_metrics().rate_limit_rejected.add(1, {"scope": scope})
                raise RateLimitExceededError(scope, retry_after)
            events.append(now)

    def _rollback_rate_limit(self, scope: str, raw_key: str) -> None:
        key = (scope, _bounded_identity(raw_key))
        with self._lock:
            events = self._rate_events.get(key)
            if events:
                events.pop()

    def _open_circuit(self, circuit: _CircuitRecord, service_identity: str, now: float) -> None:
        was_open = circuit.state == CircuitState.OPEN
        circuit.state = CircuitState.OPEN
        circuit.opened_at = now
        circuit.half_open_in_flight = 0
        if not was_open:
            get_metrics().circuit_open.add(1, {"service": service_identity})
            record_circuit_open_summary()


def _expire(events: deque[float], cutoff: float) -> None:
    while events and events[0] <= cutoff:
        events.popleft()


def _bounded_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
