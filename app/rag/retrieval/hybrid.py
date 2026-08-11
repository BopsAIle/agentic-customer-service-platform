import math
import re
import time
from collections import Counter
from collections.abc import Sequence

from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.rag.embeddings import EmbeddingProvider
from app.rag.interfaces import RetrievalMetadata
from app.rag.reranking.service import DeterministicReranker, Reranker
from app.rag.schemas import DocumentChunk, RetrievedChunk
from app.resilience.timeout import run_with_timeout


class HybridRetriever:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        reranker: Reranker | None = None,
        *,
        dense_top_k: int = 8,
        sparse_top_k: int = 8,
        rerank_candidates: int = 12,
        final_context_count: int = 4,
        reranker_timeout_seconds: float = 3.0,
        reranker_enabled: bool = True,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.reranker = reranker or DeterministicReranker()
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k
        self.rerank_candidates = rerank_candidates
        self.final_context_count = final_context_count
        self.reranker_timeout_seconds = reranker_timeout_seconds
        self.reranker_enabled = reranker_enabled
        self.backend_type = "local"
        self._chunks: dict[str, DocumentChunk] = {}
        self._vectors: dict[str, list[float]] = {}
        self.last_degraded_components: list[str] = []
        self.last_metadata: RetrievalMetadata | None = None

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        vectors = self.embedding_provider.embed_documents([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = vector
        return len(chunks)

    def reset(self) -> None:
        self._chunks.clear()
        self._vectors.clear()

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        started = time.perf_counter()
        status = "ok"
        self.last_degraded_components = []
        attributes = {
            "rag.backend": self.backend_type,
            "rag.embedding_provider": self.embedding_provider.provider_type,
            "rag.reranker_enabled": self.reranker_enabled,
        }
        with span("rag.retrieve", attributes=attributes) as retrieval_span:
            try:
                if not self._chunks:
                    results: list[RetrievedChunk] = []
                else:
                    with span("rag.embed_query"):
                        query_vector = self.embedding_provider.embed_query(query)
                    with span("rag.dense_search") as dense_span:
                        dense = sorted(
                            (
                                (chunk_id, _cosine(query_vector, vector))
                                for chunk_id, vector in self._vectors.items()
                            ),
                            key=lambda item: item[1],
                            reverse=True,
                        )[: self.dense_top_k]
                        dense_span.set_attribute("rag.dense_candidates", len(dense))
                    with span("rag.sparse_search") as sparse_span:
                        sparse = self._bm25(query)[: self.sparse_top_k]
                        sparse_span.set_attribute("rag.sparse_candidates", len(sparse))
                    dense_scores = {chunk_id: score for chunk_id, score in dense}
                    sparse_scores = {chunk_id: score for chunk_id, score in sparse}
                    candidates = set(dense_scores) | set(sparse_scores)
                    with span("rag.fusion") as fusion_span:
                        max_dense = max(dense_scores.values(), default=1.0) or 1.0
                        max_sparse = max(sparse_scores.values(), default=1.0) or 1.0
                        results = [
                            RetrievedChunk(
                                **self._chunks[chunk_id].model_dump(),
                                score=0.6 * dense_scores.get(chunk_id, 0.0) / max_dense
                                + 0.4 * sparse_scores.get(chunk_id, 0.0) / max_sparse,
                            )
                            for chunk_id in candidates
                        ]
                        results.sort(key=lambda item: item.score, reverse=True)
                        results = results[: self.rerank_candidates]
                        fusion_span.set_attribute("rag.fused_candidates", len(results))
                    if self.reranker_enabled:
                        with span("rag.rerank") as rerank_span:
                            try:
                                rerank_scores = run_with_timeout(
                                    lambda: self.reranker.score(query, results),
                                    timeout_seconds=self.reranker_timeout_seconds,
                                )
                                for result, rerank_score in zip(
                                    results, rerank_scores, strict=True
                                ):
                                    result.rerank_score = rerank_score
                                results.sort(
                                    key=lambda item: (item.rerank_score or 0.0, item.score),
                                    reverse=True,
                                )
                            except Exception:
                                self.last_degraded_components.append("reranker")
                                rerank_span.set_attribute("rag.fallback_status", "reranker")
                            rerank_span.set_attribute("rag.retrieval_count", len(results))
                    results = results[: self.final_context_count]
                fallback = "reranker" if self.last_degraded_components else "none"
                latency = time.perf_counter() - started
                self.last_metadata = RetrievalMetadata(
                    backend=self.backend_type,
                    embedding_provider=self.embedding_provider.provider_type,
                    reranker_enabled=self.reranker_enabled,
                    retrieval_count=len(results),
                    latency_seconds=latency,
                    fallback_status=fallback,
                )
                retrieval_span.set_attribute("rag.retrieval_count", len(results))
                retrieval_span.set_attribute("rag.fallback_status", fallback)
                get_metrics().rag_requests_total.add(
                    1, {"status": "ok", "backend": self.backend_type}
                )
                return results
            except Exception:
                status = "error"
                retrieval_span.set_attribute("rag.status", "error")
                get_metrics().rag_requests_total.add(
                    1, {"status": "error", "backend": self.backend_type}
                )
                raise
            finally:
                get_metrics().rag_retrieval_duration_seconds.record(
                    time.perf_counter() - started,
                    {"status": status, "backend": self.backend_type},
                )

    def _bm25(self, query: str) -> list[tuple[str, float]]:
        query_tokens = _tokens(query)
        documents = {chunk_id: _tokens(chunk.content) for chunk_id, chunk in self._chunks.items()}
        document_frequency = Counter(
            token for tokens in documents.values() for token in set(tokens)
        )
        average_length = sum(len(tokens) for tokens in documents.values()) / max(len(documents), 1)
        scores: list[tuple[str, float]] = []
        for chunk_id, tokens in documents.items():
            counts = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                if token not in counts:
                    continue
                idf = math.log(
                    (len(documents) - document_frequency[token] + 0.5)
                    / (document_frequency[token] + 0.5)
                    + 1
                )
                denominator = counts[token] + 1.5 * (
                    0.25 + 0.75 * len(tokens) / max(average_length, 1)
                )
                score += idf * counts[token] * 2.5 / denominator
            scores.append((chunk_id, score))
        return sorted(scores, key=lambda item: item[1], reverse=True)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
