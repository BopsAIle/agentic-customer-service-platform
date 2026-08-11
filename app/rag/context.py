from collections.abc import Sequence

from app.rag.schemas import RetrievedChunk


def construct_context(
    chunks: Sequence[RetrievedChunk], max_chunks: int = 4
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen_content: set[str] = set()
    for chunk in sorted(
        chunks, key=lambda item: (item.rerank_score or 0.0, item.score), reverse=True
    ):
        normalized = " ".join(chunk.content.casefold().split())
        if normalized in seen_content:
            continue
        seen_content.add(normalized)
        selected.append(chunk)
        if len(selected) >= max_chunks:
            break
    return selected
