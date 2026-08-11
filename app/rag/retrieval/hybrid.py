import math
import re
from collections import Counter
from collections.abc import Sequence

from app.rag.embeddings import EmbeddingProvider
from app.rag.reranking.service import DeterministicReranker, Reranker
from app.rag.schemas import DocumentChunk, RetrievedChunk


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
    ) -> None:
        self.embedding_provider = embedding_provider
        self.reranker = reranker or DeterministicReranker()
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k
        self.rerank_candidates = rerank_candidates
        self.final_context_count = final_context_count
        self._chunks: dict[str, DocumentChunk] = {}
        self._vectors: dict[str, list[float]] = {}

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = self.embedding_provider.embed(chunk.content)
        return len(chunks)

    def reset(self) -> None:
        self._chunks.clear()
        self._vectors.clear()

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        if not self._chunks:
            return []
        query_vector = self.embedding_provider.embed(query)
        dense = sorted(
            (
                (chunk_id, _cosine(query_vector, vector))
                for chunk_id, vector in self._vectors.items()
            ),
            key=lambda item: item[1],
            reverse=True,
        )[: self.dense_top_k]
        sparse = self._bm25(query)[: self.sparse_top_k]
        dense_scores = {chunk_id: score for chunk_id, score in dense}
        sparse_scores = {chunk_id: score for chunk_id, score in sparse}
        candidates = set(dense_scores) | set(sparse_scores)
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
        rerank_scores = self.reranker.score(query, results)
        for result, rerank_score in zip(results, rerank_scores, strict=True):
            result.rerank_score = rerank_score
        results.sort(key=lambda item: (item.rerank_score or 0.0, item.score), reverse=True)
        return results[: self.final_context_count]

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
