from typing import NoReturn

from fastapi import HTTPException, status

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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    if isinstance(error, (InvalidStateTransitionError, DuplicateActionError, ValidationError)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise error
