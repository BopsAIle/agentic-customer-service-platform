from collections.abc import Callable
from time import monotonic

from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.resilience.classification import classify_failure, is_retryable
from app.resilience.config import ResilienceConfig, Sleeper, default_sleeper
from app.resilience.errors import FailureCategory, RetryExhaustedError, UnknownWriteOutcomeError


def run_with_retry[T](
    operation: Callable[[], T],
    *,
    dependency: str,
    operation_type: str = "read",
    config: ResilienceConfig | None = None,
    sleeper: Sleeper = default_sleeper,
    timeout_seconds: float | None = None,
    clock: Callable[[], float] = monotonic,
) -> T:
    policy = config or ResilienceConfig()
    attempts_allowed = policy.max_retries + 1 if policy.enabled else 1
    # timeout_seconds is the native per-attempt deadline configured on the dependency client.
    # The retry coordinator only budgets the complete sequence; it never wraps the operation in
    # a detached thread. A dependency call must return its native timeout before this loop can
    # classify the error and schedule the next attempt.
    deadline = None
    if timeout_seconds is not None:
        backoff_budget = (
            sum(
                min(
                    policy.initial_backoff_ms * (2 ** (attempt - 1)),
                    policy.max_backoff_ms,
                )
                for attempt in range(1, attempts_allowed)
            )
            / 1000
        )
        deadline = clock() + (timeout_seconds * attempts_allowed) + backoff_budget
    last_category: FailureCategory | None = None
    for attempt in range(1, attempts_allowed + 1):
        if deadline is not None and attempt > 1 and clock() >= deadline:
            assert last_category is not None
            raise RetryExhaustedError(last_category, attempt - 1)
        try:
            return operation()
        except UnknownWriteOutcomeError:
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
            retry = attempt < attempts_allowed and is_retryable(category, operation=operation_type)
            delay = (
                min(
                    policy.initial_backoff_ms * (2 ** (attempt - 1)),
                    policy.max_backoff_ms,
                )
                / 1000
            )
            if retry and deadline is not None:
                remaining = deadline - clock()
                if remaining <= 0:
                    retry = False
                elif delay > remaining:
                    # Consume only the remaining bounded budget and fail without starting a
                    # further attempt. The prior native call has already returned at this point.
                    delay = remaining
                    retry = False
            get_metrics().dependency_failures_total.add(
                1, {"dependency": dependency, "failure_category": category.value}
            )
            with span(
                "resilience.retry" if retry else "resilience.recovery",
                attributes={
                    "dependency.name": dependency,
                    "failure.category": category.value,
                    "retry.attempt": attempt,
                    "retry.exhausted": not retry,
                    "recovery.action": "retry" if retry else "fail_safely",
                },
            ):
                if retry:
                    get_metrics().retry_attempts_total.add(1, {"dependency": dependency})
                    sleeper(delay)
                    continue
                if not is_retryable(category, operation=operation_type):
                    raise
                get_metrics().retry_exhausted_total.add(
                    1, {"dependency": dependency, "failure_category": category.value}
                )
                raise RetryExhaustedError(category, attempt) from error
    assert last_category is not None
    raise RetryExhaustedError(last_category, attempts_allowed)
