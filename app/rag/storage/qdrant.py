from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.rag.embeddings import EmbeddingProvider
from app.rag.schemas import DocumentChunk

QDRANT_DENSE_DISTANCE = "Cosine"


def build_dense_vector_params(dimension: int) -> Any:
    """Build the one unnamed dense-vector schema used by ingestion and readiness."""

    from qdrant_client.http import models

    return models.VectorParams(size=dimension, distance=models.Distance.COSINE)


class QdrantKnowledgeStore:
    """Qdrant dense-vector persistence adapter; hybrid ranking remains in the retrieval service."""

    def __init__(
        self,
        url: str,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        from qdrant_client import QdrantClient

        self.client = QdrantClient(url=url, timeout=_native_timeout(timeout_seconds))
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.timeout_seconds = timeout_seconds

    def ensure_collection(self, dimension: int) -> None:
        exists = self.client.collection_exists(self.collection_name)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=build_dense_vector_params(dimension),
                timeout=_native_timeout(self.timeout_seconds),
            )

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        from qdrant_client.http import models

        vectors = self.embedding_provider.embed_documents([chunk.content for chunk in chunks])
        dimension = (
            len(vectors[0]) if vectors else len(self.embedding_provider.embed_query("probe"))
        )
        self.ensure_collection(dimension)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),
                    vector=vector,
                    payload=chunk.model_dump(),
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
            timeout=_native_timeout(self.timeout_seconds),
        )
        return len(chunks)

    def close(self) -> None:
        self.client.close()


def _native_timeout(seconds: float) -> int:
    """Qdrant's HTTP API accepts whole-second server deadlines only."""

    return max(1, int(seconds))
