from dataclasses import dataclass
from enum import IntEnum, StrEnum


class OperationType(StrEnum):
    READ = "read"
    WRITE = "write"


class RiskLevel(IntEnum):
    READ_ONLY = 0
    LOW = 1
    CONFIRMATION_REQUIRED = 2
    HUMAN_HANDLING = 3


class ToolError(Exception):
    """Base class for deterministic business-tool failures."""


class ResourceNotFoundError(ToolError):
    def __init__(self, resource: str, resource_id: int) -> None:
        super().__init__(f"{resource} {resource_id} was not found")


class OwnershipError(ToolError):
    def __init__(self, resource: str, resource_id: int, customer_id: int) -> None:
        super().__init__(f"{resource} {resource_id} does not belong to customer {customer_id}")


class InvalidStateTransitionError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DuplicateActionError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ValidationError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    description: str
    operation_type: OperationType
    risk_level: RiskLevel
