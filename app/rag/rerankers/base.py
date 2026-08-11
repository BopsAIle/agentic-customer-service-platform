from collections.abc import Sequence
from typing import Protocol

from app.rag.schemas import RetrievedChunk


class Reranker(Protocol):
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]: ...
