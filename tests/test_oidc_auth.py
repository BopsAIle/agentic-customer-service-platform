import json
import logging
import time
from collections.abc import Callable

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import get_current_principal, resolve_customer_scope
from app.auth.models import (
    ActorType,
    AuthenticationCredentials,
    CredentialScheme,
    PrincipalType,
)
from app.auth.oidc import OIDCAuthenticator, OIDCConfiguration
from app.auth.protocols import AuthenticationFailureReason, InvalidCredentialsError

ISSUER = "https://identity.example.test"
AUDIENCE = "agent-control-plane"
JWKS_URI = "https://identity.example.test/keys"


def _key(key_id: str) -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    return private_key, jwk


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "operator-123",
        "exp": now + 300,
        "iat": now,
        "email": "operator@example.test",
        "roles": ["support_operator"],
        "groups": ["refund-operations"],
        "tenant_id": "tenant-a",
        "customer_ids": [1, 2],
    }
    claims.update(overrides)
    return claims


def _token(
    private_key: rsa.RSAPrivateKey,
    key_id: str,
    claims: dict[str, object] | None = None,
) -> str:
    return jwt.encode(
        claims or _claims(),
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _credentials(token: str) -> AuthenticationCredentials:
    return AuthenticationCredentials(scheme=CredentialScheme.BEARER, secret=token)


def _client(jwks: Callable[[], list[dict[str, object]]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URI})
        if str(request.url) == JWKS_URI:
            return httpx.Response(200, json={"keys": jwks()})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _authenticator(
    jwks: Callable[[], list[dict[str, object]]],
) -> OIDCAuthenticator:
    return OIDCAuthenticator(
        OIDCConfiguration(issuer=ISSUER, audience=AUDIENCE),
        http_client=_client(jwks),
    )


def test_valid_oidc_token_maps_bounded_principal() -> None:
    private_key, public_key = _key("valid-key")

    principal = _authenticator(lambda: [public_key]).authenticate(
        _credentials(_token(private_key, "valid-key"))
    )

    assert principal.actor_type == ActorType.SUPPORT_OPERATOR
    assert principal.principal_type == PrincipalType.OIDC
    assert principal.subject == "operator-123"
    assert principal.email == "operator@example.test"
    assert principal.roles == ["support_operator"]
    assert principal.groups == ["refund-operations"]
    assert principal.tenant_id == "tenant-a"
    assert principal.customer_ids == [1, 2]
    assert principal.actor_id.startswith("oidc:")
    assert "operator-123" not in principal.actor_id
    assert "subject" not in principal.model_dump(mode="json")
    assert "email" not in principal.model_dump(mode="json")


@pytest.mark.parametrize(
    ("claims", "expected_reason"),
    [
        (_claims(exp=int(time.time()) - 120), AuthenticationFailureReason.EXPIRED),
        (_claims(iss="https://wrong.example.test"), AuthenticationFailureReason.WRONG_ISSUER),
        (_claims(aud="wrong-audience"), AuthenticationFailureReason.WRONG_AUDIENCE),
        (_claims(roles=[]), AuthenticationFailureReason.MISSING_ROLE),
    ],
)
def test_oidc_token_validation_failures_are_bounded(
    claims: dict[str, object], expected_reason: AuthenticationFailureReason
) -> None:
    private_key, public_key = _key("validation-key")

    with pytest.raises(InvalidCredentialsError) as captured:
        _authenticator(lambda: [public_key]).authenticate(
            _credentials(_token(private_key, "validation-key", claims))
        )

    assert captured.value.reason == expected_reason


def test_invalid_signature_is_rejected_after_one_rotation_refresh() -> None:
    trusted_private, trusted_public = _key("shared-key")
    untrusted_private, _ = _key("shared-key")
    del trusted_private
    calls = 0

    def jwks() -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [trusted_public]

    with pytest.raises(InvalidCredentialsError) as captured:
        _authenticator(jwks).authenticate(_credentials(_token(untrusted_private, "shared-key")))

    assert captured.value.reason == AuthenticationFailureReason.INVALID_SIGNATURE
    assert calls == 2


def test_unknown_kid_refreshes_jwks_and_accepts_rotated_key() -> None:
    old_private, old_public = _key("old-key")
    new_private, new_public = _key("new-key")
    del old_private
    calls = 0

    def jwks() -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [old_public] if calls == 1 else [new_public]

    principal = _authenticator(jwks).authenticate(_credentials(_token(new_private, "new-key")))

    assert principal.principal_type == PrincipalType.OIDC
    assert calls == 2


def test_oidc_customer_scope_is_revalidated_by_server_scope_resolver() -> None:
    private_key, public_key = _key("tenant-key")
    principal = _authenticator(lambda: [public_key]).authenticate(
        _credentials(_token(private_key, "tenant-key"))
    )

    assert resolve_customer_scope(principal, 2).customer_id == 2
    with pytest.raises(HTTPException) as captured:
        resolve_customer_scope(principal, 3)

    assert captured.value.status_code == 404


def test_customer_principal_is_bound_to_exact_validated_customer_scope() -> None:
    private_key, public_key = _key("customer-key")
    token = _token(
        private_key,
        "customer-key",
        _claims(roles=["customer"], customer_ids=[2], sub="customer-subject"),
    )

    principal = _authenticator(lambda: [public_key]).authenticate(_credentials(token))

    assert principal.actor_type == ActorType.CUSTOMER
    assert principal.customer_id == 2
    assert resolve_customer_scope(principal, None).customer_id == 2
    with pytest.raises(HTTPException) as captured:
        resolve_customer_scope(principal, 1)
    assert captured.value.status_code == 404


def test_tokens_and_pii_claims_are_not_logged_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trusted_private, trusted_public = _key("trusted-key")
    untrusted_private, _ = _key("trusted-key")
    del trusted_private
    token = _token(
        untrusted_private,
        "trusted-key",
        _claims(email="private-operator@example.test"),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(InvalidCredentialsError):
        _authenticator(lambda: [trusted_public]).authenticate(_credentials(token))

    assert token not in caplog.text
    assert "private-operator@example.test" not in caplog.text


def test_authentication_metrics_use_only_bounded_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key = _key("metric-key")
    token = _token(private_key, "metric-key")
    events: list[tuple[int, dict[str, object]]] = []

    class Counter:
        def add(self, value: int, attributes: dict[str, object]) -> None:
            events.append((value, attributes))

    class Metrics:
        authentication_attempts_total = Counter()

    monkeypatch.setattr("app.auth.dependencies.get_metrics", lambda: Metrics())
    principal = get_current_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        _authenticator(lambda: [public_key]),
    )

    assert principal.principal_type == PrincipalType.OIDC
    assert events == [
        (
            1,
            {
                "auth_success": True,
                "auth_failure_reason": "none",
                "principal_type": "oidc",
            },
        )
    ]
    assert token not in repr(events)
    assert "operator@example.test" not in repr(events)


def test_authentication_failure_metric_records_bounded_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key = _key("expired-metric-key")
    token = _token(
        private_key,
        "expired-metric-key",
        _claims(exp=int(time.time()) - 120),
    )
    events: list[tuple[int, dict[str, object]]] = []

    class Counter:
        def add(self, value: int, attributes: dict[str, object]) -> None:
            events.append((value, attributes))

    class Metrics:
        authentication_attempts_total = Counter()

    monkeypatch.setattr("app.auth.dependencies.get_metrics", lambda: Metrics())
    with pytest.raises(HTTPException) as captured:
        get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            _authenticator(lambda: [public_key]),
        )

    assert captured.value.status_code == 401
    assert events == [
        (
            1,
            {
                "auth_success": False,
                "auth_failure_reason": "expired",
                "principal_type": "unknown",
            },
        )
    ]
    assert token not in repr(events)
