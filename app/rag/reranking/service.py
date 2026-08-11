from collections.abc import Sequence
from typing import Any, cast

from app.rag.rerankers.base import Reranker as Reranker
from app.rag.rerankers.deterministic import DeterministicReranker as DeterministicReranker
from app.rag.schemas import RetrievedChunk


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
