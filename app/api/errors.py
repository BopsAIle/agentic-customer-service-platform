from typing import NoReturn

from fastapi import HTTPException, status

from app.resilience.errors import UnknownWriteOutcomeError
from app.tools.base import (
    DuplicateActionError,
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
    ToolError,
    ValidationError,
)


def raise_http_for_tool_error(error: ToolError) -> NoReturn:
    if isinstance(error, ResourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, OwnershipError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        ) from error
    if isinstance(error, (InvalidStateTransitionError, DuplicateActionError, ValidationError)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise error


def raise_http_for_unknown_write(error: UnknownWriteOutcomeError) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Write outcome is unknown. Do not submit a new request; retry with the same "
            "Idempotency-Key to reconcile safely."
        ),
        headers={"Retry-After": "1"},
    ) from error
