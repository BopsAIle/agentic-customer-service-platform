from collections.abc import Callable
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.backends import DisabledAuthenticator, StaticBearerAuthenticator
from app.auth.models import AuthenticationCredentials, CredentialScheme, Principal
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


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
