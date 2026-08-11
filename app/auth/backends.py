import hashlib
import hmac
import json
from collections.abc import Mapping

from pydantic import SecretStr, ValidationError

from app.auth.models import AuthenticationCredentials, CredentialScheme, Principal
from app.auth.protocols import (
    AuthenticationConfigurationError,
    AuthenticationUnavailableError,
    InvalidCredentialsError,
)


class StaticBearerAuthenticator:
    """Development authenticator backed by configured opaque bearer tokens.

    Raw tokens are hashed during construction and are not retained.
    """

    def __init__(self, principals_by_token: Mapping[str, Principal]) -> None:
        if not principals_by_token:
            raise AuthenticationConfigurationError
        self._principals_by_digest = {
            self._digest(token): principal.model_copy(deep=True)
            for token, principal in principals_by_token.items()
            if token
        }
        if len(self._principals_by_digest) != len(principals_by_token):
            raise AuthenticationConfigurationError

    @classmethod
    def from_json(cls, configuration: SecretStr | str) -> "StaticBearerAuthenticator":
        raw_configuration = (
            configuration.get_secret_value()
            if isinstance(configuration, SecretStr)
            else configuration
        )
        try:
            payload = json.loads(raw_configuration)
            if not isinstance(payload, dict):
                raise TypeError
            principals = {
                token: Principal.model_validate(value)
                for token, value in payload.items()
                if isinstance(token, str)
            }
            if len(principals) != len(payload):
                raise TypeError
            return cls(principals)
        except (json.JSONDecodeError, TypeError, ValidationError):
            raise AuthenticationConfigurationError from None

    def authenticate(self, credentials: AuthenticationCredentials) -> Principal:
        if credentials.scheme != CredentialScheme.BEARER:
            raise InvalidCredentialsError
        candidate_digest = self._digest(credentials.secret.get_secret_value())
        matched_principal: Principal | None = None
        for configured_digest, principal in self._principals_by_digest.items():
            if hmac.compare_digest(candidate_digest, configured_digest):
                matched_principal = principal
        if matched_principal is None:
            raise InvalidCredentialsError
        return matched_principal.model_copy(deep=True)

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()


class DisabledAuthenticator:
    def authenticate(self, credentials: AuthenticationCredentials) -> Principal:
        del credentials
        raise AuthenticationUnavailableError
