from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.rag.embeddings import EmbeddingProvider
from app.rag.interfaces import KnowledgeFilter, RetrievalMetadata
from app.rag.rerankers import Reranker
from app.rag.retrieval.lexical import (
    LEXICAL_METADATA_KEY,
    LEXICAL_VECTOR_NAME,
    LexicalIndex,
)
from app.rag.schemas import RetrievedChunk
from app.rag.storage.qdrant import QDRANT_DENSE_DISTANCE

logger = logging.getLogger(__name__)


class QdrantReadinessCategory(StrEnum):
    READY = "ready"
    QDRANT_UNREACHABLE = "qdrant_unreachable"
    COLLECTION_MISSING = "collection_missing"
    VECTOR_SCHEMA_MISMATCH = "vector_schema_mismatch"
    VECTOR_DIMENSION_MISMATCH = "vector_dimension_mismatch"
    KNOWLEDGE_NOT_INGESTED = "knowledge_not_ingested"


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
        embedding_dimension: int | None = None,
        dense_top_k: int = 8,
        sparse_top_k: int = 8,
        filters: KnowledgeFilter | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from qdrant_client import QdrantClient

            # Qdrant owns the request deadline. Do not wrap this synchronous client in a
            # detached thread; a native timeout guarantees a retry starts only after the
            # previous request has returned.
            client = QdrantClient(url=url, timeout=_native_timeout(timeout_seconds))
        self.client = client
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.reranker_enabled = reranker_enabled
        self.rerank_candidates = rerank_candidates
        self.final_context_count = final_context_count
        self.timeout_seconds = timeout_seconds
        self.reranker_timeout_seconds = reranker_timeout_seconds
        self.embedding_dimension = embedding_dimension or getattr(
            embedding_provider, "dimension", None
        )
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k
        self.filters = filters
        self.last_degraded_components: list[str] = []
        self.last_metadata: RetrievalMetadata | None = None
        self.last_readiness_category = "not_checked"
        self._lexical_index: LexicalIndex | None = None

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
                query_filter = self._query_filter()
                with span("rag.dense_search") as dense_span:
                    dense_prefetch = self._dense_prefetch(vector, query_filter)
                    dense_span.set_attribute("rag.dense_candidates", self.dense_top_k)
                lexical_index = self._lexical_index_for_query()
                sparse_indices, sparse_values = lexical_index.encode_query(query)
                if sparse_indices:
                    from qdrant_client.http import models

                    with span("rag.sparse_search") as sparse_span:
                        sparse_prefetch = models.Prefetch(
                            query=models.SparseVector(
                                indices=sparse_indices,
                                values=sparse_values,
                            ),
                            using=LEXICAL_VECTOR_NAME,
                            filter=query_filter,
                            limit=self.sparse_top_k,
                        )
                        sparse_span.set_attribute("rag.sparse_candidates", self.sparse_top_k)
                    with span("rag.fusion") as fusion_span:
                        response = self.client.query_points(
                            collection_name=self.collection_name,
                            query=models.FusionQuery(fusion=models.Fusion.RRF),
                            prefetch=[dense_prefetch, sparse_prefetch],
                            limit=self.rerank_candidates,
                            with_payload=True,
                            with_vectors=False,
                            timeout=_native_timeout(self.timeout_seconds),
                        )
                        fusion_span.set_attribute("rag.fused_candidates", len(response.points))
                else:
                    response = self.client.query_points(
                        collection_name=self.collection_name,
                        query=vector,
                        query_filter=query_filter,
                        limit=self.rerank_candidates,
                        with_payload=True,
                        with_vectors=False,
                        timeout=_native_timeout(self.timeout_seconds),
                    )
                results = self._validated_results(response.points)
                if self.reranker_enabled and self.reranker is not None and results:
                    reranker = self.reranker
                    with span("rag.rerank") as rerank_span:
                        try:
                            # Rerankers are synchronous providers. Network-backed providers
                            # must enforce their own native deadline; local CPU rerankers are
                            # allowed to finish and failures retain the fused ranking.
                            scores = reranker.score(query, results)
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
        try:
            collection = self.client.get_collection(self.collection_name)
        except Exception as error:
            category = (
                QdrantReadinessCategory.COLLECTION_MISSING
                if _is_collection_missing(error)
                else QdrantReadinessCategory.QDRANT_UNREACHABLE
            )
            self._record_readiness_failure(category)
            return False

        config = getattr(collection, "config", None)
        params = _field(config, "params")
        vectors = _field(params, "vectors")
        if isinstance(vectors, dict) or vectors is None:
            self._record_readiness_failure(QdrantReadinessCategory.VECTOR_SCHEMA_MISMATCH)
            return False

        sparse_vectors = _field(params, "sparse_vectors")
        sparse_config = (
            sparse_vectors.get(LEXICAL_VECTOR_NAME) if isinstance(sparse_vectors, dict) else None
        )
        if sparse_config is None or _field(sparse_config, "index") is None:
            self._record_readiness_failure(QdrantReadinessCategory.VECTOR_SCHEMA_MISMATCH)
            return False

        actual_dimension = _field(vectors, "size")
        if actual_dimension != self.embedding_dimension:
            self._record_readiness_failure(
                QdrantReadinessCategory.VECTOR_DIMENSION_MISMATCH,
                actual_dimension=actual_dimension,
            )
            return False

        actual_distance = _enum_value(_field(vectors, "distance"))
        if actual_distance != QDRANT_DENSE_DISTANCE:
            self._record_readiness_failure(
                QdrantReadinessCategory.VECTOR_SCHEMA_MISMATCH,
                actual_dimension=actual_dimension,
                actual_distance=actual_distance,
            )
            return False

        metadata = _field(config, "metadata")
        lexical_metadata = _field(metadata, LEXICAL_METADATA_KEY)
        try:
            lexical_index = LexicalIndex.from_metadata(lexical_metadata)
        except ValueError:
            self._record_readiness_failure(QdrantReadinessCategory.VECTOR_SCHEMA_MISMATCH)
            return False

        points_count = _field(collection, "points_count")
        if not isinstance(points_count, int) or points_count < 1:
            self._record_readiness_failure(
                QdrantReadinessCategory.KNOWLEDGE_NOT_INGESTED,
                actual_dimension=actual_dimension,
                actual_distance=actual_distance,
                points_count=points_count,
            )
            return False

        self.last_readiness_category = QdrantReadinessCategory.READY.value
        self._lexical_index = lexical_index
        return True

    def _record_readiness_failure(
        self,
        category: QdrantReadinessCategory,
        *,
        actual_dimension: object | None = None,
        actual_distance: object | None = None,
        points_count: object | None = None,
    ) -> None:
        self.last_readiness_category = category.value
        logger.warning(
            "Qdrant readiness check failed.",
            extra={
                "readiness_dependency": "qdrant",
                "readiness_category": category.value,
                "qdrant_collection": self.collection_name,
                "expected_dimension": self.embedding_dimension,
                "actual_dimension": actual_dimension,
                "actual_distance": actual_distance,
                "points_count": points_count,
            },
        )

    def _query_filter(self) -> Any | None:
        if self.filters is None:
            return None
        from qdrant_client.http import models

        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in self.filters.model_dump(exclude_none=True).items()
        ]
        return models.Filter(must=conditions) if conditions else None

    def _dense_prefetch(self, vector: list[float], query_filter: Any | None) -> Any:
        from qdrant_client.http import models

        return models.Prefetch(
            query=vector,
            filter=query_filter,
            limit=self.dense_top_k,
        )

    def _lexical_index_for_query(self) -> LexicalIndex:
        if self._lexical_index is not None:
            return self._lexical_index
        collection = self.client.get_collection(self.collection_name)
        config = _field(collection, "config")
        metadata = _field(config, "metadata")
        lexical_metadata = _field(metadata, LEXICAL_METADATA_KEY)
        self._lexical_index = LexicalIndex.from_metadata(lexical_metadata)
        return self._lexical_index

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


def _native_timeout(seconds: float) -> int:
    """Qdrant's HTTP API accepts whole-second server deadlines only."""

    return max(1, int(seconds))


def _field(value: object, name: str) -> object | None:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _is_collection_missing(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 404 or "not found" in str(error).casefold()
