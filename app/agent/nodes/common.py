from pydantic import BaseModel

from app.agent.schemas import AgentErrorCategory
from app.tools.base import (
    DuplicateActionError,
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
    ToolError,
)


def error_category(error: Exception) -> AgentErrorCategory:
    if isinstance(error, ResourceNotFoundError):
        return AgentErrorCategory.RESOURCE_NOT_FOUND
    if isinstance(error, OwnershipError):
        return AgentErrorCategory.OWNERSHIP_VIOLATION
    if isinstance(error, InvalidStateTransitionError):
        return AgentErrorCategory.INVALID_STATE
    if isinstance(error, DuplicateActionError):
        return AgentErrorCategory.DUPLICATE_ACTION
    if isinstance(error, ToolError):
        return AgentErrorCategory.INVALID_TOOL_ARGUMENTS
    return AgentErrorCategory.LLM_ERROR


def serialise_result(result: object) -> dict[str, object]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in result
            ]
        }
    return {"value": result}
