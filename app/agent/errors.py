from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import httpx
from sqlalchemy.exc import DBAPIError, OperationalError

from app.agent.schemas import AgentErrorCategory
from app.resilience.classification import classify_failure
from app.resilience.errors import ResilienceError, UnknownWriteOutcomeError
from app.tools.base import (
    DuplicateActionError,
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
    ToolError,
)


class RuntimeFailureSource(StrEnum):
    """The bounded component boundary where an exception was observed."""

    LLM = "llm"
    TOOL = "tool"
    DEPENDENCY = "dependency"
    MEMORY = "memory"
    POLICY = "policy"
    AUDIT = "audit"
    PROJECTION = "projection"
    CHECKPOINT = "checkpoint"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class RuntimeErrorClassification:
    """Safe public category plus the existing detailed resilience reason."""

    category: AgentErrorCategory
    failure_category: str | None = None


def classify_runtime_error(
    error: BaseException, *, source: RuntimeFailureSource
) -> RuntimeErrorClassification:
    """Classify a failure without using exception text or exposing its payload.

    This high-level category intentionally does not decide retryability. The resilience
    coordinator remains authoritative for retry and unknown-write behavior.
    """

    if isinstance(error, UnknownWriteOutcomeError):
        return RuntimeErrorClassification(
            AgentErrorCategory.UNKNOWN_WRITE_OUTCOME,
            error.category.value,
        )

    if isinstance(error, ResilienceError):
        category = (
            AgentErrorCategory.LLM_ERROR
            if source == RuntimeFailureSource.LLM
            else AgentErrorCategory.DEPENDENCY_ERROR
        )
        return RuntimeErrorClassification(category, error.category.value)

    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        dependency = (
            source.value
            if source
            in {
                RuntimeFailureSource.LLM,
                RuntimeFailureSource.TOOL,
            }
            else "database"
        )
        return RuntimeErrorClassification(
            AgentErrorCategory.LLM_ERROR
            if source == RuntimeFailureSource.LLM
            else AgentErrorCategory.DEPENDENCY_ERROR,
            classify_failure(error, dependency=dependency, operation="write").value,
        )

    if isinstance(error, (OperationalError, DBAPIError)):
        return RuntimeErrorClassification(
            AgentErrorCategory.DEPENDENCY_ERROR,
            classify_failure(error, dependency="database", operation="write").value,
        )

    if isinstance(error, ConnectionError):
        return RuntimeErrorClassification(
            AgentErrorCategory.LLM_ERROR
            if source == RuntimeFailureSource.LLM
            else AgentErrorCategory.DEPENDENCY_ERROR,
            "llm_unavailable"
            if source == RuntimeFailureSource.LLM
            else "unknown_dependency_failure",
        )

    if source == RuntimeFailureSource.LLM:
        return RuntimeErrorClassification(AgentErrorCategory.LLM_ERROR, "llm_unavailable")

    if source == RuntimeFailureSource.TOOL:
        domain_category = _known_tool_category(error)
        if domain_category is not None:
            return RuntimeErrorClassification(domain_category)
        if isinstance(error, ToolError):
            return RuntimeErrorClassification(AgentErrorCategory.TOOL_ERROR, "tool_failure")
        if isinstance(error, ValueError):
            return RuntimeErrorClassification(AgentErrorCategory.TOOL_ERROR, "tool_failure")
        return RuntimeErrorClassification(AgentErrorCategory.INTERNAL_ERROR, "internal_error")

    if source in {
        RuntimeFailureSource.DEPENDENCY,
        RuntimeFailureSource.MEMORY,
        RuntimeFailureSource.AUDIT,
        RuntimeFailureSource.PROJECTION,
        RuntimeFailureSource.CHECKPOINT,
    }:
        return RuntimeErrorClassification(AgentErrorCategory.DEPENDENCY_ERROR)

    if source == RuntimeFailureSource.POLICY:
        return RuntimeErrorClassification(AgentErrorCategory.INTERNAL_ERROR, "internal_error")

    return RuntimeErrorClassification(AgentErrorCategory.INTERNAL_ERROR, "internal_error")


def _known_tool_category(error: BaseException) -> AgentErrorCategory | None:
    if isinstance(error, ResourceNotFoundError):
        return AgentErrorCategory.RESOURCE_NOT_FOUND
    if isinstance(error, OwnershipError):
        return AgentErrorCategory.OWNERSHIP_VIOLATION
    if isinstance(error, InvalidStateTransitionError):
        return AgentErrorCategory.INVALID_STATE
    if isinstance(error, DuplicateActionError):
        return AgentErrorCategory.DUPLICATE_ACTION
    return None
