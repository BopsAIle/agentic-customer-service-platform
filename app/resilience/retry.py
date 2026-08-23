from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx

from app.observability.metrics import get_metrics, record_retry_summary
from app.observability.tracing import span
from app.resilience.classification import classify_failure, is_retryable
from app.resilience.config import ResilienceConfig, Sleeper, default_sleeper
from app.resilience.control import CircuitState, ReliabilityController
from app.resilience.errors import (
    FailureCategory,
    RateLimitExceededError,
    RetryBudgetExhaustedError,
    RetryExhaustedError,
    UnknownWriteOutcomeError,
)


def run_with_retry[T](
    operation: Callable[[], T],
    *,
    dependency: str,
    operation_type: str = "read",
    config: ResilienceConfig | None = None,
    controller: ReliabilityController | None = None,
    service_identity: str | None = None,
    provider_rate_limit: bool = False,
    sleeper: Sleeper = default_sleeper,
    timeout_seconds: float | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = monotonic,
    random_source: Callable[[], float] = random.random,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> T:
    """Execute replay-safe work with bounded, deadline-aware retries.

    Dependency calls retain their native timeout. Writes and unknown write outcomes are never
    replayed. A supplied controller adds persistent per-service circuit, bulkhead, retry-budget,
    and provider-rate state; standalone calls remain supported for tests and adapters.
    """

    policy = config or ResilienceConfig()
    attempts_allowed = policy.max_retries + 1 if policy.enabled else 1
    identity = service_identity or dependency
    effective_deadline = (
        deadline
        if deadline is not None
        else _sequence_deadline(clock(), timeout_seconds, attempts_allowed, policy)
    )
    last_category: FailureCategory | None = None
    attempts_started = 0

    for attempt in range(1, attempts_allowed + 1):
        if effective_deadline is not None and clock() >= effective_deadline:
            category = last_category or FailureCategory.UNKNOWN_DEPENDENCY_FAILURE
            _record_retry_exhausted(dependency, category)
            raise RetryExhaustedError(category, attempts_started)
        operation_started = False
        try:
            if controller is not None:
                with controller.bulkhead(identity, dependency):
                    controller.before_call(identity)
                    try:
                        if provider_rate_limit:
                            controller.enforce_provider_limit(identity)
                    except RateLimitExceededError:
                        controller.cancel_call(identity)
                        raise
                    attempts_started += 1
                    operation_started = True
                    result = operation()
                controller.record_success(identity)
                return result
            attempts_started += 1
            return operation()
        except UnknownWriteOutcomeError:
            if controller is not None:
                controller.record_failure(identity)
            get_metrics().dependency_failures_total.add(
                1,
                {
                    "dependency": dependency,
                    "failure_category": FailureCategory.TOOL_TIMEOUT.value,
                },
            )
            raise
        except Exception as error:
            category = classify_failure(error, dependency=dependency, operation=operation_type)
            last_category = category
            replay_safe = is_retryable(category, operation=operation_type)
            if (
                controller is not None
                and operation_started
                and (replay_safe or controller.circuit_state(identity) == CircuitState.HALF_OPEN)
            ):
                controller.record_failure(identity)
            retry = attempt < attempts_allowed and replay_safe
            delay = _retry_delay(
                error,
                attempt=attempt,
                policy=policy,
                random_source=random_source,
                wall_clock=wall_clock,
            )
            if retry and controller is not None and not controller.consume_retry_budget(identity):
                category = FailureCategory.RETRY_BUDGET_EXHAUSTED
                last_category = category
                retry = False
            if retry and effective_deadline is not None:
                remaining = effective_deadline - clock()
                next_attempt_budget = timeout_seconds or 0.0
                if remaining <= next_attempt_budget:
                    retry = False
                elif delay > remaining - next_attempt_budget:
                    delay = max(0.0, remaining - next_attempt_budget)
            get_metrics().dependency_failures_total.add(
                1, {"dependency": dependency, "failure_category": category.value}
            )
            with span(
                "resilience.retry" if retry else "resilience.recovery",
                attributes={
                    "dependency.name": dependency,
                    "service.identity": identity,
                    "failure.category": category.value,
                    "retry.attempt": attempt,
                    "retry.exhausted": not retry,
                    "recovery.action": "retry" if retry else "fail_safely",
                },
            ):
                if retry:
                    _record_retry_attempt(dependency, identity)
                    sleeper(delay)
                    continue
                if not replay_safe:
                    raise
                _record_retry_exhausted(dependency, category)
                if category == FailureCategory.RETRY_BUDGET_EXHAUSTED:
                    raise RetryBudgetExhaustedError(identity) from error
                raise RetryExhaustedError(category, attempts_started) from error

    assert last_category is not None
    _record_retry_exhausted(dependency, last_category)
    raise RetryExhaustedError(last_category, attempts_started)


def _sequence_deadline(
    started: float,
    timeout_seconds: float | None,
    attempts_allowed: int,
    policy: ResilienceConfig,
) -> float | None:
    if timeout_seconds is None:
        return None
    backoff_budget = (
        sum(
            min(policy.initial_backoff_ms * (2 ** (attempt - 1)), policy.max_backoff_ms)
            for attempt in range(1, attempts_allowed)
        )
        / 1000
    )
    return float(started + (timeout_seconds * attempts_allowed) + backoff_budget)


def _retry_delay(
    error: Exception,
    *,
    attempt: int,
    policy: ResilienceConfig,
    random_source: Callable[[], float],
    wall_clock: Callable[[], datetime],
) -> float:
    base = min(policy.initial_backoff_ms * (2 ** (attempt - 1)), policy.max_backoff_ms) / 1000
    jitter_sample = min(1.0, max(0.0, random_source()))
    jitter_factor = 1 + policy.jitter_ratio * ((2 * jitter_sample) - 1)
    jittered = max(0.0, base * jitter_factor)
    retry_after = _retry_after_seconds(error, wall_clock())
    if retry_after is None:
        return float(jittered)
    return float(max(jittered, min(retry_after, policy.max_retry_after_seconds)))


def _retry_after_seconds(error: Exception, now: datetime) -> float | None:
    response = error.response if isinstance(error, httpx.HTTPStatusError) else None
    raw = response.headers.get("Retry-After") if response is not None else None
    if raw is None:
        value = getattr(error, "retry_after_seconds", None)
        return float(value) if isinstance(value, (int, float)) and value >= 0 else None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - now).total_seconds())


def _record_retry_attempt(dependency: str, service_identity: str) -> None:
    attributes = {"dependency": dependency, "service": service_identity}
    metrics = get_metrics()
    metrics.retry_attempts_total.add(1, attributes)
    metrics.retry_attempt_count.add(1, attributes)
    record_retry_summary()


def _record_retry_exhausted(dependency: str, category: FailureCategory) -> None:
    attributes = {"dependency": dependency, "failure_category": category.value}
    metrics = get_metrics()
    metrics.retry_exhausted_total.add(1, attributes)
    metrics.retry_exhausted.add(1, attributes)
    record_retry_summary(exhausted=True)
