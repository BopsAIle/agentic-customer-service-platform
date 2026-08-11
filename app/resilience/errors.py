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


class ResilienceError(Exception):
    def __init__(self, category: FailureCategory, message: str = "dependency failure") -> None:
        super().__init__(message)
        self.category = category


class RetryExhaustedError(ResilienceError):
    def __init__(self, category: FailureCategory, attempts: int) -> None:
        super().__init__(category, "bounded dependency retries were exhausted")
        self.attempts = attempts


class UnknownWriteOutcomeError(ResilienceError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            FailureCategory.TOOL_TIMEOUT,
            f"the outcome of {tool_name} could not be confirmed",
        )
        self.tool_name = tool_name
