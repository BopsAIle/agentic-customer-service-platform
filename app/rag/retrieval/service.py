from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.rag.backends.local import LocalKnowledgeBackend
from app.rag.backends.qdrant import QdrantKnowledgeBackend
from app.rag.config import RagBackend
from app.rag.embeddings import build_embedding_provider
from app.rag.ingestion.chunking import chunk_document
from app.rag.ingestion.loader import load_markdown_documents
from app.rag.interfaces import (
    KnowledgeIndexer,
    KnowledgeRetriever,
    ManagedKnowledgeRetriever,
    ReadyKnowledgeRetriever,
)
from app.rag.rerankers import DeterministicReranker
from app.rag.schemas import DocumentChunk, KnowledgeDocument, RetrievedChunk


class KnowledgeService:
    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self.retriever = retriever

    def ingest_directory(self, directory: Path, chunk_size: int = 800) -> int:
        documents = load_markdown_documents(directory)
        return self.ingest_documents(documents, chunk_size=chunk_size)

    def ingest_documents(
        self, documents: Sequence[KnowledgeDocument], *, chunk_size: int = 800
    ) -> int:
        chunks: list[DocumentChunk] = []
        for document in documents:
            chunks.extend(chunk_document(document, max_chars=chunk_size))
        if not isinstance(self.retriever, KnowledgeIndexer):
            raise RuntimeError("The configured knowledge backend does not support ingestion.")
        return self.retriever.upsert(chunks)

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        return self.retriever.retrieve(query)

    def reset(self) -> None:
        if not isinstance(self.retriever, KnowledgeIndexer):
            raise RuntimeError("The configured knowledge backend does not support reset.")
        self.retriever.reset()

    def close(self) -> None:
        if isinstance(self.retriever, ManagedKnowledgeRetriever):
            self.retriever.close()

    def is_ready(self) -> bool:
        if isinstance(self.retriever, ReadyKnowledgeRetriever):
            return self.retriever.is_ready()
        return True

    @property
    def last_degraded_components(self) -> list[str]:
        return list(getattr(self.retriever, "last_degraded_components", []))

    @property
    def last_metadata(self) -> object | None:
        return getattr(self.retriever, "last_metadata", None)

    @property
    def backend_type(self) -> str:
        return str(getattr(self.retriever, "backend_type", "unknown"))


def build_knowledge_service(
    settings: Settings, *, qdrant_client: Any | None = None
) -> KnowledgeService:
    # A retrieval attempt is the logical operation boundary. Network-backed embedding and
    # Qdrant calls must not have a native deadline longer than that attempt's budget.
    embedding_provider = build_embedding_provider(
        settings,
        timeout_seconds=min(settings.embedding_timeout_seconds, settings.retrieval_timeout_seconds),
        connect_timeout_seconds=min(
            settings.embedding_connect_timeout_seconds,
            settings.retrieval_timeout_seconds,
        ),
    )
    reranker = DeterministicReranker() if settings.reranker_enabled else None
    backend = RagBackend(settings.rag_backend)
    if backend is RagBackend.LOCAL:
        retriever: KnowledgeRetriever = LocalKnowledgeBackend(
            embedding_provider,
            reranker=reranker,
            dense_top_k=settings.rag_dense_top_k,
            sparse_top_k=settings.rag_sparse_top_k,
            rerank_candidates=settings.rag_rerank_candidates,
            final_context_count=settings.rag_final_context_count,
            reranker_timeout_seconds=settings.rag_reranker_timeout_seconds,
            reranker_enabled=settings.reranker_enabled,
        )
    else:
        retriever = QdrantKnowledgeBackend(
            url=settings.qdrant_url,
            collection_name=settings.qdrant_collection,
            embedding_provider=embedding_provider,
            reranker=reranker,
            reranker_enabled=settings.reranker_enabled,
            rerank_candidates=settings.rag_rerank_candidates,
            final_context_count=settings.rag_final_context_count,
            # Retrieval owns the logical attempt budget. Keep Qdrant's native request
            # deadline at or below it so a retry cannot overlap an abandoned call.
            timeout_seconds=min(
                settings.qdrant_timeout_seconds, settings.retrieval_timeout_seconds
            ),
            reranker_timeout_seconds=settings.rag_reranker_timeout_seconds,
            client=qdrant_client,
        )
    service = KnowledgeService(retriever)
    if backend is RagBackend.LOCAL:
        service.ingest_directory(Path(__file__).parents[2] / "knowledge", settings.rag_chunk_size)
    return service


def build_default_knowledge_service(settings: Settings) -> KnowledgeService:
    """Compatibility name retained for existing runtime callers."""
    return build_knowledge_service(settings)


__all__ = [
    "KnowledgeRetriever",
    "KnowledgeService",
    "build_default_knowledge_service",
    "build_knowledge_service",
]
