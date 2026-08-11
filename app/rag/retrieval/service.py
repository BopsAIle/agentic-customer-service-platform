from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.ingestion.chunking import chunk_document
from app.rag.ingestion.loader import load_markdown_documents
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.schemas import DocumentChunk, KnowledgeDocument, RetrievedChunk


class KnowledgeRetriever(Protocol):
    def retrieve(self, query: str) -> list[RetrievedChunk]: ...


class KnowledgeService:
    def __init__(self, retriever: HybridRetriever) -> None:
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
        return self.retriever.upsert(chunks)

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        return self.retriever.retrieve(query)

    def reset(self) -> None:
        self.retriever.reset()


def build_default_knowledge_service(settings: Settings) -> KnowledgeService:
    retriever = HybridRetriever(
        DeterministicEmbeddingProvider(),
        dense_top_k=settings.rag_dense_top_k,
        sparse_top_k=settings.rag_sparse_top_k,
        rerank_candidates=settings.rag_rerank_candidates,
        final_context_count=settings.rag_final_context_count,
    )
    service = KnowledgeService(retriever)
    service.ingest_directory(Path(__file__).parents[2] / "knowledge", settings.rag_chunk_size)
    return service
