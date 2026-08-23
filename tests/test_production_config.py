from scripts.validate_production_config import validate_production_environment


def _valid_config() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "DEBUG": "false",
        "AUTH_MODE": "oidc",
        "AGENT_DECISION_CONTRACT_VERSION": "semantic_decision_v3",
        "DATABASE_URL": "postgresql+psycopg://runtime:secret@postgres:5432/customer_service",
        "OIDC_ISSUER": "https://identity.example.test",
        "OIDC_AUDIENCE": "agent-control-plane",
        "LLM_API_KEY": "configured-by-secret-manager",
        "CHECKPOINT_BACKEND": "postgres",
        "POLICY_AUDIT_BACKEND": "postgres",
        "AGENT_RUN_PROJECTION_BACKEND": "postgres",
        "EVIDENCE_STORE_BACKEND": "s3",
        "EVIDENCE_STORE_BUCKET": "immutable-evidence",
        "OTEL_ENABLED": "true",
        "LOCAL_DEMO_AUTH_TOKEN": "",
    }


def test_production_config_accepts_explicit_safe_configuration() -> None:
    assert validate_production_environment(_valid_config()) == []


def test_production_config_rejects_demo_and_local_defaults() -> None:
    values = _valid_config()
    values.update(
        {
            "AUTH_MODE": "local_demo",
            "DEBUG": "true",
            "DATABASE_URL": "postgresql+psycopg://app:app@localhost:5432/customer_service",
            "LOCAL_DEMO_AUTH_TOKEN": "local-demo-token",
        }
    )
    errors = validate_production_environment(values)
    assert "AUTH_MODE must be oidc" in errors
    assert "DEBUG must be disabled" in errors
    assert "DATABASE_URL must not use local development defaults" in errors
    assert "LOCAL_DEMO_AUTH_TOKEN must not be configured in production" in errors
