import re
from collections.abc import Sequence

from app.rag.schemas import RetrievedChunk


class DeterministicReranker:
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
        return [
            len(query_tokens.intersection(re.findall(r"[a-z0-9]+", chunk.content.casefold())))
            / max(len(query_tokens), 1)
            for chunk in chunks
        ]
