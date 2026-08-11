import pytest
from pydantic import ValidationError

from app.core.config import AuthenticationMode, Settings


def test_production_rejects_local_demo_authentication() -> None:
    with pytest.raises(ValidationError, match="local_demo authentication is restricted"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode=AuthenticationMode.LOCAL_DEMO,
            local_demo_auth_token="not-a-production-secret",
        )


def test_production_rejects_missing_authentication() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        Settings(_env_file=None, app_env="production", auth_mode=AuthenticationMode.DISABLED)


def test_production_static_authentication_requires_configured_principals() -> None:
    with pytest.raises(ValidationError, match="non-empty AUTH_TOKENS_JSON"):
        Settings(_env_file=None, app_env="production", auth_mode=AuthenticationMode.STATIC)
