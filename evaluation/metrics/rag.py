import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.interfaces import KnowledgeRetriever, RetrievalMetadata


def citation_integrity(
    citations: Sequence[dict[str, Any]], retrieved: Sequence[dict[str, Any]]
) -> bool:
    valid = {
        str(item.get("citation_id") or f"{item.get('document_id')}#{item.get('section')}")
        for item in retrieved
    }
    return all(item.get("citation_id") in valid and item.get("source") for item in citations)


@dataclass(frozen=True, slots=True)
class RuntimeRagEvaluation:
    retrieval_success: bool
    citation_availability: bool
    reranker_used: bool
    fallback_used: bool
    latency_ms: float
    backend: str


def evaluate_runtime_retrieval(retriever: KnowledgeRetriever, query: str) -> RuntimeRagEvaluation:
    """Provider-neutral runtime hook; it records no query or document content."""
    started = time.perf_counter()
    try:
        chunks = retriever.retrieve(query)
    except Exception:
        return RuntimeRagEvaluation(
            retrieval_success=False,
            citation_availability=False,
            reranker_used=False,
            fallback_used=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            backend=str(getattr(retriever, "backend_type", "unknown")),
        )
    metadata = getattr(retriever, "last_metadata", None)
    safe_metadata = metadata if isinstance(metadata, RetrievalMetadata) else None
    return RuntimeRagEvaluation(
        retrieval_success=bool(chunks),
        citation_availability=bool(chunks)
        and all(bool(chunk.citation_id and chunk.source) for chunk in chunks),
        reranker_used=any(chunk.rerank_score is not None for chunk in chunks),
        fallback_used=(safe_metadata is not None and safe_metadata.fallback_status != "none"),
        latency_ms=(time.perf_counter() - started) * 1000,
        backend=(
            safe_metadata.backend
            if safe_metadata is not None
            else str(getattr(retriever, "backend_type", "unknown"))
        ),
    )
