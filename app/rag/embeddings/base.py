from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Provider-neutral embedding boundary for ingestion and retrieval."""

    provider_type: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
