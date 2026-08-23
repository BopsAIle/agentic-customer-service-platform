from enum import StrEnum
from typing import Protocol

from app.auth.models import AuthenticationCredentials, Principal


class AuthenticationFailureReason(StrEnum):
    MISSING_CREDENTIALS = "missing_credentials"
    INVALID_CREDENTIALS = "invalid_credentials"
    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"
    WRONG_ISSUER = "wrong_issuer"
    WRONG_AUDIENCE = "wrong_audience"
    MISSING_ROLE = "missing_role"
    INVALID_CLAIMS = "invalid_claims"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"


class AuthenticationError(Exception):
    """Base error for authentication failures with a credential-safe message."""

    reason: AuthenticationFailureReason

    def __init__(self, message: str, reason: AuthenticationFailureReason) -> None:
        self.reason = reason
        super().__init__(message)


class InvalidCredentialsError(AuthenticationError):
    def __init__(
        self,
        reason: AuthenticationFailureReason = AuthenticationFailureReason.INVALID_CREDENTIALS,
    ) -> None:
        super().__init__("Authentication failed.", reason)


class AuthenticationUnavailableError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Authentication is unavailable.", AuthenticationFailureReason.UNAVAILABLE)


class AuthenticationConfigurationError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__(
            "Authentication configuration is invalid.",
            AuthenticationFailureReason.MISCONFIGURED,
        )


class Authenticator(Protocol):
    """Framework-neutral authentication provider boundary."""

    def authenticate(self, credentials: AuthenticationCredentials) -> Principal: ...
