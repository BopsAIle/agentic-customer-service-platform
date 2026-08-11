import hashlib
import math
import re
from collections.abc import Sequence


class DeterministicEmbeddingProvider:
    """Stable, offline embeddings for tests, evaluation, and local development."""

    provider_type = "deterministic"

    def __init__(self, dimension: int = 32) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"[a-z0-9]+", text.casefold()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed(self, text: str) -> list[float]:
        """Compatibility alias for pre-Sprint 10.1.6 callers."""
        return self.embed_query(text)
