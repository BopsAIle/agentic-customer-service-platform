from typing import Protocol

from app.auth.models import AuthenticationCredentials, Principal


class AuthenticationError(Exception):
    """Base error for authentication failures with a credential-safe message."""


class InvalidCredentialsError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Authentication failed.")


class AuthenticationUnavailableError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Authentication is unavailable.")


class AuthenticationConfigurationError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Authentication configuration is invalid.")


class Authenticator(Protocol):
    """Framework-neutral authentication provider boundary."""

    def authenticate(self, credentials: AuthenticationCredentials) -> Principal: ...
