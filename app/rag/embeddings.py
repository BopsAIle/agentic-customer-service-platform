import hashlib
import math
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


class DeterministicEmbeddingProvider:
    def __init__(self, dimension: int = 32) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"[a-z0-9]+", text.casefold()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
