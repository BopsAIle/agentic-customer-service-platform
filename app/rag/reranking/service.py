import re
from collections.abc import Sequence
from typing import Any, Protocol, cast

from app.rag.schemas import RetrievedChunk


class Reranker(Protocol):
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]: ...


class DeterministicReranker:
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
        return [
            len(query_tokens.intersection(re.findall(r"[a-z0-9]+", chunk.content.casefold())))
            / max(len(query_tokens), 1)
            for chunk in chunks
        ]


class CrossEncoderReranker:
    """Optional lazy cross-encoder adapter; tests use DeterministicReranker."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: object | None = None

    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        model = cast(Any, self._model)
        return [
            float(value) for value in model.predict([(query, chunk.content) for chunk in chunks])
        ]
