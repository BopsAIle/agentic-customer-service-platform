from collections.abc import Callable

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
) -> T:
    policy = config or ResilienceConfig()
    attempts_allowed = policy.max_retries + 1 if policy.enabled else 1
    last_category: FailureCategory | None = None
    for attempt in range(1, attempts_allowed + 1):
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
                    delay_ms = min(
                        policy.initial_backoff_ms * (2 ** (attempt - 1)),
                        policy.max_backoff_ms,
                    )
                    sleeper(delay_ms / 1000)
                    continue
                if not is_retryable(category, operation=operation_type):
                    raise
                get_metrics().retry_exhausted_total.add(
                    1, {"dependency": dependency, "failure_category": category.value}
                )
                raise RetryExhaustedError(category, attempt) from error
    assert last_category is not None
    raise RetryExhaustedError(last_category, attempts_allowed)
