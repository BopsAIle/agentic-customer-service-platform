import pytest
from pydantic import ValidationError

from app.core.config import AuthenticationMode, LLMProvider, Settings


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


def test_deterministic_integration_provider_is_restricted_to_integration_demo() -> None:
    with pytest.raises(ValidationError, match="APP_ENV=integration and AUTH_MODE=local_demo"):
        Settings(
            _env_file=None,
            app_env="development",
            llm_provider=LLMProvider.DETERMINISTIC_INTEGRATION,
        )


def test_structured_output_mode_defaults_to_schema() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_structured_output_mode == "schema"


def test_function_calling_structured_output_mode_is_accepted() -> None:
    settings = Settings(_env_file=None, llm_structured_output_mode="function_calling")

    assert settings.llm_structured_output_mode == "function_calling"


def test_invalid_structured_output_mode_fails_settings_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_structured_output_mode="json_mode")


def test_deterministic_integration_provider_rejects_static_authentication() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=local_demo"):
        Settings(
            _env_file=None,
            app_env="integration",
            auth_mode=AuthenticationMode.STATIC,
            auth_tokens_json=(
                '{"integration-token":{"actor_id":"operator",'
                '"actor_type":"support_operator","roles":["support_operator"]}}'
            ),
            llm_provider=LLMProvider.DETERMINISTIC_INTEGRATION,
            agent_run_projection_backend="postgres",
        )


def test_integration_environment_explicitly_accepts_test_provider_and_demo_auth() -> None:
    settings = Settings(
        _env_file=None,
        app_env="integration",
        auth_mode=AuthenticationMode.LOCAL_DEMO,
        local_demo_auth_token="integration-only-token",
        llm_provider=LLMProvider.DETERMINISTIC_INTEGRATION,
        agent_run_projection_backend="postgres",
    )

    assert settings.llm_provider == LLMProvider.DETERMINISTIC_INTEGRATION


def test_integration_rejects_process_local_run_projection_storage() -> None:
    with pytest.raises(ValidationError, match="agent-run projection storage"):
        Settings(
            _env_file=None,
            app_env="integration",
            auth_mode=AuthenticationMode.LOCAL_DEMO,
            local_demo_auth_token="integration-only-token",
            llm_provider=LLMProvider.DETERMINISTIC_INTEGRATION,
            agent_run_projection_backend="memory",
        )
