"""Validate production configuration without printing secret values."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

_PLACEHOLDERS = {"", "change-me", "changeme", "example", "validation-only", "local-demo"}


def validate_production_environment(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []

    def required(name: str) -> str | None:
        value = values.get(name, "").strip()
        if not value or value.casefold() in _PLACEHOLDERS:
            errors.append(f"{name} is missing or still uses a placeholder")
            return None
        return value

    if values.get("APP_ENV", "").casefold() != "production":
        errors.append("APP_ENV must be production")
    if values.get("DEBUG", "false").casefold() in {"1", "true", "yes", "on"}:
        errors.append("DEBUG must be disabled")
    if values.get("AUTH_MODE", "").casefold() != "oidc":
        errors.append("AUTH_MODE must be oidc")
    if values.get("AGENT_DECISION_CONTRACT_VERSION", "semantic_decision_v3") != (
        "semantic_decision_v3"
    ):
        errors.append("AGENT_DECISION_CONTRACT_VERSION must be semantic_decision_v3")
    for name in ("DATABASE_URL", "OIDC_ISSUER", "OIDC_AUDIENCE", "LLM_API_KEY"):
        required(name)
    issuer = values.get("OIDC_ISSUER", "")
    if issuer and not issuer.startswith("https://"):
        errors.append("OIDC_ISSUER must use HTTPS")
    database_url = values.get("DATABASE_URL", "")
    if database_url and any(token in database_url.casefold() for token in ("localhost", "app:app")):
        errors.append("DATABASE_URL must not use local development defaults")
    if values.get("CHECKPOINT_BACKEND", "") != "postgres":
        errors.append("CHECKPOINT_BACKEND must be postgres")
    if values.get("POLICY_AUDIT_BACKEND", "") != "postgres":
        errors.append("POLICY_AUDIT_BACKEND must be postgres")
    if values.get("AGENT_RUN_PROJECTION_BACKEND", "") != "postgres":
        errors.append("AGENT_RUN_PROJECTION_BACKEND must be postgres")
    if values.get("EVIDENCE_STORE_BACKEND", "s3") != "s3":
        errors.append("EVIDENCE_STORE_BACKEND must be s3 for production")
    if values.get("EVIDENCE_STORE_BACKEND") == "s3":
        required("EVIDENCE_STORE_BUCKET")
    if values.get("OTEL_ENABLED", "false").casefold() not in {"1", "true", "yes", "on"}:
        errors.append("OTEL_ENABLED should be enabled for production operations")
    if values.get("LOCAL_DEMO_AUTH_TOKEN", "").strip():
        errors.append("LOCAL_DEMO_AUTH_TOKEN must not be configured in production")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors = validate_production_environment(os.environ)
    if errors:
        print("production config validation: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("production config validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
