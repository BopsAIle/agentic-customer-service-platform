from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Agentic Customer Service Platform")
    app_env: str = Field(default="development")
    debug: bool = False
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/customer_service"
    )
    llm_model: str = "llama3.1"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str | None = None
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0)
    confirmation_ttl_seconds: int = Field(default=300, gt=0)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "customer_service_knowledge"
    rag_dense_top_k: int = Field(default=8, gt=0)
    rag_sparse_top_k: int = Field(default=8, gt=0)
    rag_rerank_candidates: int = Field(default=12, gt=0)
    rag_final_context_count: int = Field(default=4, gt=0)
    rag_chunk_size: int = Field(default=800, gt=100)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
