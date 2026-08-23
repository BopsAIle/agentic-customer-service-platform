from enum import StrEnum


class FailureCategory(StrEnum):
    LLM_TIMEOUT = "llm_timeout"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_MALFORMED_OUTPUT = "llm_malformed_output"
    DATABASE_TRANSIENT = "database_transient"
    DATABASE_UNAVAILABLE = "database_unavailable"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_TRANSIENT_FAILURE = "tool_transient_failure"
    TOOL_PERMANENT_FAILURE = "tool_permanent_failure"
    RETRIEVAL_TIMEOUT = "retrieval_timeout"
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"
    RETRIEVAL_EMPTY = "retrieval_empty"
    RERANKER_FAILURE = "reranker_failure"
    EMBEDDING_FAILURE = "embedding_failure"
    POLICY_FAILURE = "policy_failure"
    MEMORY_FAILURE = "memory_failure"
    UNKNOWN_DEPENDENCY_FAILURE = "unknown_dependency_failure"
    CIRCUIT_OPEN = "circuit_open"
    BULKHEAD_REJECTED = "bulkhead_rejected"
    RATE_LIMITED = "rate_limited"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"


class ResilienceError(Exception):
    def __init__(self, category: FailureCategory, message: str = "dependency failure") -> None:
        super().__init__(message)
        self.category = category


class RetryExhaustedError(ResilienceError):
    def __init__(self, category: FailureCategory, attempts: int) -> None:
        super().__init__(category, "bounded dependency retries were exhausted")
        self.attempts = attempts


class CircuitOpenError(ResilienceError):
    def __init__(self, service_identity: str) -> None:
        super().__init__(FailureCategory.CIRCUIT_OPEN, "dependency circuit is open")
        self.service_identity = service_identity


class BulkheadRejectedError(ResilienceError):
    def __init__(self, service_identity: str) -> None:
        super().__init__(FailureCategory.BULKHEAD_REJECTED, "dependency capacity is exhausted")
        self.service_identity = service_identity


class RateLimitExceededError(ResilienceError):
    def __init__(self, scope: str, retry_after_seconds: float) -> None:
        super().__init__(FailureCategory.RATE_LIMITED, "bounded request rate was exceeded")
        self.scope = scope
        self.retry_after_seconds = max(0.0, retry_after_seconds)


class RetryBudgetExhaustedError(ResilienceError):
    def __init__(self, service_identity: str) -> None:
        super().__init__(FailureCategory.RETRY_BUDGET_EXHAUSTED, "retry budget was exhausted")
        self.service_identity = service_identity


class UnknownWriteOutcomeError(ResilienceError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            FailureCategory.TOOL_TIMEOUT,
            f"the outcome of {tool_name} could not be confirmed",
        )
        self.tool_name = tool_name


class AuditPersistenceError(ResilienceError):
    """Durable audit storage failed; callers must preserve fail-closed semantics."""

    def __init__(self) -> None:
        super().__init__(FailureCategory.UNKNOWN_DEPENDENCY_FAILURE, "audit persistence failed")
