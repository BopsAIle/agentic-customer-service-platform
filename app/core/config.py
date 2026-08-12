import json
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.models import Principal


class AuthenticationMode(StrEnum):
    DISABLED = "disabled"
    LOCAL_DEMO = "local_demo"
    STATIC = "static"


class LLMProvider(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    DETERMINISTIC_INTEGRATION = "deterministic_integration"


class Settings(BaseSettings):
    app_name: str = Field(default="Agentic Customer Service Platform")
    app_env: str = Field(default="development")
    debug: bool = False
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/customer_service"
    )
    llm_model: str = "llama3.1"
    llm_provider: LLMProvider = LLMProvider.OPENAI_COMPATIBLE
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str | None = None
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0)
    confirmation_ttl_seconds: int = Field(default=300, gt=0)
    rag_backend: str = Field(default="qdrant", pattern="^(qdrant|local)$")
    embedding_provider: str = Field(
        default="deterministic", pattern="^(deterministic|openai|huggingface)$"
    )
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=32, gt=0)
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0.0)
    reranker_enabled: bool = True
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "customer_service_knowledge"
    rag_dense_top_k: int = Field(default=8, gt=0)
    rag_sparse_top_k: int = Field(default=8, gt=0)
    rag_rerank_candidates: int = Field(default=12, gt=0)
    rag_final_context_count: int = Field(default=4, gt=0)
    rag_chunk_size: int = Field(default=800, gt=100)
    rag_reranker_timeout_seconds: float = Field(default=3.0, gt=0.0)
    qdrant_timeout_seconds: float = Field(default=10.0, gt=0.0)
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "agentic-customer-service-platform"
    memory_enabled: bool = True
    memory_max_context_items: int = Field(default=5, gt=0, le=20)
    memory_default_ttl_days: int = Field(default=365, ge=0)
    memory_support_context_ttl_days: int = Field(default=30, gt=0)
    resilience_enabled: bool = True
    resilience_max_retries: int = Field(default=2, ge=0, le=5)
    resilience_initial_backoff_ms: int = Field(default=100, ge=0, le=5000)
    resilience_max_backoff_ms: int = Field(default=500, ge=0, le=10000)
    retrieval_timeout_seconds: float = Field(default=5.0, gt=0.0)
    tool_timeout_seconds: float = Field(default=10.0, gt=0.0)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    database_query_timeout_seconds: float = Field(default=10.0, gt=0.0)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0.0)
    auth_mode: AuthenticationMode = AuthenticationMode.DISABLED
    local_demo_auth_token: SecretStr | None = None
    local_demo_actor_id: str = Field(default="operator-local-demo", min_length=1, max_length=200)
    auth_tokens_json: SecretStr = SecretStr("{}")
    checkpoint_backend: str = Field(default="postgres", pattern="^(postgres|memory)$")
    policy_audit_backend: str = Field(default="postgres", pattern="^(postgres|memory)$")
    policy_audit_memory_limit: int = Field(default=500, gt=0, le=5000)
    policy_audit_query_limit: int = Field(default=50, gt=0, le=100)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_authentication_mode(self) -> "Settings":
        environment = self.app_env.casefold()
        if self.auth_mode == AuthenticationMode.LOCAL_DEMO:
            if environment not in {"development", "demo", "test", "integration"}:
                raise ValueError(
                    "local_demo authentication is restricted to development/demo/integration"
                )
            if (
                self.local_demo_auth_token is None
                or not self.local_demo_auth_token.get_secret_value()
            ):
                raise ValueError("local_demo authentication requires LOCAL_DEMO_AUTH_TOKEN")
        if self.auth_mode == AuthenticationMode.STATIC:
            try:
                configured_tokens = json.loads(self.auth_tokens_json.get_secret_value())
                if (
                    not isinstance(configured_tokens, dict)
                    or not configured_tokens
                    or any(not isinstance(token, str) or not token for token in configured_tokens)
                ):
                    raise TypeError
                for configured_principal in configured_tokens.values():
                    Principal.model_validate(configured_principal)
            except (json.JSONDecodeError, TypeError, ValidationError):
                raise ValueError(
                    "static authentication requires a non-empty AUTH_TOKENS_JSON"
                ) from None
        if environment == "production" and self.auth_mode != AuthenticationMode.STATIC:
            raise ValueError("production requires an explicitly configured authentication backend")
        if environment in {"production", "integration"} and self.policy_audit_backend != "postgres":
            raise ValueError("production and integration require PostgreSQL policy audit storage")
        if self.llm_provider == LLMProvider.DETERMINISTIC_INTEGRATION and (
            environment != "integration" or self.auth_mode != AuthenticationMode.LOCAL_DEMO
        ):
            raise ValueError(
                "deterministic_integration LLM provider requires "
                "APP_ENV=integration and AUTH_MODE=local_demo"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
