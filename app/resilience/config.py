from collections.abc import Callable
from dataclasses import dataclass
from time import sleep

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class ResilienceConfig:
    enabled: bool = True
    max_retries: int = 2
    initial_backoff_ms: int = 100
    max_backoff_ms: int = 500
    jitter_ratio: float = 0.2
    retry_budget_attempts: int = 100
    retry_budget_window_seconds: float = 60.0
    max_retry_after_seconds: float = 30.0
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    circuit_half_open_attempts: int = 1
    bulkhead_default_limit: int = 32
    bulkhead_provider_limit: int = 8
    bulkhead_wait_seconds: float = 0.0
    principal_rate_limit: int = 600
    customer_rate_limit: int = 600
    provider_rate_limit: int = 600
    rate_limit_window_seconds: float = 60.0
    llm_timeout_seconds: float = 30.0
    retrieval_timeout_seconds: float = 5.0
    reranker_timeout_seconds: float = 3.0
    tool_timeout_seconds: float = 10.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResilienceConfig":
        return cls(
            enabled=settings.resilience_enabled,
            max_retries=settings.resilience_max_retries,
            initial_backoff_ms=settings.resilience_initial_backoff_ms,
            max_backoff_ms=settings.resilience_max_backoff_ms,
            jitter_ratio=settings.resilience_jitter_ratio,
            retry_budget_attempts=settings.resilience_retry_budget_attempts,
            retry_budget_window_seconds=settings.resilience_retry_budget_window_seconds,
            max_retry_after_seconds=settings.resilience_max_retry_after_seconds,
            circuit_failure_threshold=settings.resilience_circuit_failure_threshold,
            circuit_recovery_seconds=settings.resilience_circuit_recovery_seconds,
            circuit_half_open_attempts=settings.resilience_circuit_half_open_attempts,
            bulkhead_default_limit=settings.resilience_bulkhead_default_limit,
            bulkhead_provider_limit=settings.resilience_bulkhead_provider_limit,
            bulkhead_wait_seconds=settings.resilience_bulkhead_wait_seconds,
            principal_rate_limit=settings.resilience_principal_rate_limit,
            customer_rate_limit=settings.resilience_customer_rate_limit,
            provider_rate_limit=settings.resilience_provider_rate_limit,
            rate_limit_window_seconds=settings.resilience_rate_limit_window_seconds,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            retrieval_timeout_seconds=settings.retrieval_timeout_seconds,
            reranker_timeout_seconds=settings.rag_reranker_timeout_seconds,
            tool_timeout_seconds=settings.tool_timeout_seconds,
        )


Sleeper = Callable[[float], None]


def default_sleeper(seconds: float) -> None:
    sleep(seconds)
