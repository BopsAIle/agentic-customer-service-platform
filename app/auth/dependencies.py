from collections.abc import Callable
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.backends import DisabledAuthenticator, StaticBearerAuthenticator
from app.auth.models import (
    ActorType,
    AuthenticationCredentials,
    CredentialScheme,
    CustomerScope,
    Principal,
)
from app.auth.protocols import AuthenticationError, Authenticator
from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_authenticator() -> Authenticator:
    settings = get_settings()
    if not settings.auth_enabled:
        return DisabledAuthenticator()
    return StaticBearerAuthenticator.from_json(settings.auth_tokens_json)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    authenticator: Authenticator = Depends(get_authenticator),
) -> Principal:
    if credentials is None:
        raise _authentication_error("Authentication required.")
    try:
        return authenticator.authenticate(
            AuthenticationCredentials(
                scheme=CredentialScheme(credentials.scheme.casefold()),
                secret=credentials.credentials,
            )
        )
    except (AuthenticationError, ValueError):
        raise _authentication_error("Invalid authentication credentials.") from None


def require_role(role: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if role not in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return principal

    return dependency


def require_support_operator(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if (
        principal.actor_type != ActorType.SUPPORT_OPERATOR
        or "support_operator" not in principal.roles
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions.",
        )
    return principal


def resolve_customer_scope(
    principal: Principal, requested_customer_id: int | None
) -> CustomerScope:
    """Resolve a caller-supplied customer ID against authenticated identity."""

    if principal.actor_type == ActorType.CUSTOMER:
        if principal.customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer identity is not scoped.",
            )
        if requested_customer_id is not None and requested_customer_id != principal.customer_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found.",
            )
        return CustomerScope(customer_id=principal.customer_id, principal=principal)
    if principal.actor_type == ActorType.SUPPORT_OPERATOR:
        if "support_operator" not in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        if requested_customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer scope is required.",
            )
        return CustomerScope(customer_id=requested_customer_id, principal=principal)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions.",
    )


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
