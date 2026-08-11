from __future__ import annotations

import time
from collections.abc import Sequence
from math import ceil
from typing import Any

from pydantic import ValidationError

from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.rag.embeddings import EmbeddingProvider
from app.rag.interfaces import KnowledgeFilter, RetrievalMetadata
from app.rag.rerankers import Reranker
from app.rag.schemas import RetrievedChunk
from app.resilience.timeout import run_with_timeout


class QdrantKnowledgeBackend:
    """Production retrieval adapter backed by a configured Qdrant collection."""

    backend_type = "qdrant"

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        reranker: Reranker | None,
        reranker_enabled: bool,
        rerank_candidates: int,
        final_context_count: int,
        timeout_seconds: float,
        reranker_timeout_seconds: float,
        filters: KnowledgeFilter | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=url, timeout=ceil(timeout_seconds))
        self.client = client
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.reranker_enabled = reranker_enabled
        self.rerank_candidates = rerank_candidates
        self.final_context_count = final_context_count
        self.timeout_seconds = timeout_seconds
        self.reranker_timeout_seconds = reranker_timeout_seconds
        self.filters = filters
        self.last_degraded_components: list[str] = []
        self.last_metadata: RetrievalMetadata | None = None

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        started = time.perf_counter()
        status = "ok"
        fallback = "none"
        self.last_degraded_components = []
        attributes = {
            "rag.backend": self.backend_type,
            "rag.embedding_provider": self.embedding_provider.provider_type,
            "rag.reranker_enabled": self.reranker_enabled,
        }
        with span("rag.retrieve", attributes=attributes) as retrieval_span:
            try:
                with span("rag.embed_query"):
                    vector = self.embedding_provider.embed_query(query)
                response = run_with_timeout(
                    lambda: self.client.query_points(
                        collection_name=self.collection_name,
                        query=vector,
                        query_filter=self._query_filter(),
                        limit=self.rerank_candidates,
                        with_payload=True,
                        with_vectors=False,
                        timeout=ceil(self.timeout_seconds),
                    ),
                    timeout_seconds=self.timeout_seconds,
                )
                results = self._validated_results(response.points)
                if self.reranker_enabled and self.reranker is not None and results:
                    reranker = self.reranker
                    with span("rag.rerank") as rerank_span:
                        try:
                            scores = run_with_timeout(
                                lambda: reranker.score(query, results),
                                timeout_seconds=self.reranker_timeout_seconds,
                            )
                            for result, score in zip(results, scores, strict=True):
                                result.rerank_score = score
                            results.sort(
                                key=lambda item: (item.rerank_score or 0.0, item.score),
                                reverse=True,
                            )
                        except Exception:
                            fallback = "reranker"
                            self.last_degraded_components.append("reranker")
                            rerank_span.set_attribute("rag.fallback_status", fallback)
                results = results[: self.final_context_count]
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
                    1, {"status": status, "backend": self.backend_type}
                )
                return results
            except Exception:
                status = "error"
                retrieval_span.set_attribute("rag.status", status)
                get_metrics().rag_requests_total.add(
                    1, {"status": status, "backend": self.backend_type}
                )
                raise
            finally:
                get_metrics().rag_retrieval_duration_seconds.record(
                    time.perf_counter() - started,
                    {"status": status, "backend": self.backend_type},
                )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def is_ready(self) -> bool:
        run_with_timeout(
            self.client.get_collections,
            timeout_seconds=self.timeout_seconds,
        )
        return True

    def _query_filter(self) -> Any | None:
        if self.filters is None:
            return None
        from qdrant_client.http import models

        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in self.filters.model_dump(exclude_none=True).items()
        ]
        return models.Filter(must=conditions) if conditions else None

    @staticmethod
    def _validated_results(points: Sequence[Any]) -> list[RetrievedChunk]:
        results: list[RetrievedChunk] = []
        for point in points:
            payload = point.payload
            if not isinstance(payload, dict):
                continue
            try:
                results.append(RetrievedChunk.model_validate({**payload, "score": point.score}))
            except ValidationError:
                continue
        return results
