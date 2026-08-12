from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.rag.schemas import DocumentChunk, RetrievedChunk


@dataclass(frozen=True, slots=True)
class RetrievalMetadata:
    """Safe operational metadata for a retrieval attempt."""

    backend: str
    embedding_provider: str
    reranker_enabled: bool
    retrieval_count: int
    latency_seconds: float
    fallback_status: str = "none"
    hybrid: bool = False
    fusion_strategy: str = "none"
    dense_candidate_count: int = 0
    sparse_candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """The complete, request-scoped output of one retrieval operation."""

    chunks: tuple[RetrievedChunk, ...]
    metadata: RetrievalMetadata
    degraded_components: tuple[str, ...] = ()


class KnowledgeFilter(BaseModel):
    """Allowlisted knowledge metadata filters; arbitrary payload filters are not accepted."""

    category: str | None = None
    document_id: str | None = None
    source: str | None = None


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Application boundary used by the agent for knowledge retrieval."""

    def retrieve(self, query: str) -> RetrievalResult: ...


@runtime_checkable
class KnowledgeIndexer(Protocol):
    def upsert(self, chunks: Sequence[DocumentChunk]) -> int: ...

    def reset(self) -> None: ...


@runtime_checkable
class ManagedKnowledgeRetriever(Protocol):
    def close(self) -> None: ...


@runtime_checkable
class ReadyKnowledgeRetriever(Protocol):
    def is_ready(self) -> bool: ...
