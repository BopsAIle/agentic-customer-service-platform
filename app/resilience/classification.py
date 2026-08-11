from sqlalchemy.exc import DBAPIError, OperationalError

from app.resilience.errors import FailureCategory, ResilienceError
from app.tools.base import ToolError


def classify_failure(
    error: BaseException, *, dependency: str, operation: str = "read"
) -> FailureCategory:
    if isinstance(error, ResilienceError):
        return error.category
    if isinstance(error, TimeoutError):
        return {
            "llm": FailureCategory.LLM_TIMEOUT,
            "retrieval": FailureCategory.RETRIEVAL_TIMEOUT,
            "tool": FailureCategory.TOOL_TIMEOUT,
        }.get(dependency, FailureCategory.UNKNOWN_DEPENDENCY_FAILURE)
    if dependency == "llm" and isinstance(error, (ValueError, TypeError)):
        return FailureCategory.LLM_MALFORMED_OUTPUT
    if isinstance(error, (OperationalError, DBAPIError)):
        return (
            FailureCategory.DATABASE_UNAVAILABLE
            if dependency == "database"
            else FailureCategory.DATABASE_TRANSIENT
        )
    if isinstance(error, ToolError):
        return FailureCategory.TOOL_PERMANENT_FAILURE
    if dependency == "retrieval":
        return FailureCategory.RETRIEVAL_UNAVAILABLE
    if dependency == "memory":
        return FailureCategory.MEMORY_FAILURE
    if dependency == "policy":
        return FailureCategory.POLICY_FAILURE
    if dependency == "llm":
        return FailureCategory.LLM_UNAVAILABLE
    if dependency == "tool":
        return (
            FailureCategory.TOOL_TRANSIENT_FAILURE
            if operation == "read"
            else FailureCategory.TOOL_PERMANENT_FAILURE
        )
    return FailureCategory.UNKNOWN_DEPENDENCY_FAILURE


def is_retryable(category: FailureCategory, *, operation: str = "read") -> bool:
    if operation == "write":
        return False
    return category in {
        FailureCategory.LLM_TIMEOUT,
        FailureCategory.LLM_UNAVAILABLE,
        FailureCategory.LLM_MALFORMED_OUTPUT,
        FailureCategory.DATABASE_TRANSIENT,
        FailureCategory.DATABASE_UNAVAILABLE,
        FailureCategory.TOOL_TIMEOUT,
        FailureCategory.TOOL_TRANSIENT_FAILURE,
        FailureCategory.RETRIEVAL_TIMEOUT,
        FailureCategory.RETRIEVAL_UNAVAILABLE,
        FailureCategory.EMBEDDING_FAILURE,
    }
