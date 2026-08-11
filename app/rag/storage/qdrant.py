from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from app.rag.embeddings import EmbeddingProvider
from app.rag.schemas import DocumentChunk


class QdrantKnowledgeStore:
    """Qdrant dense-vector persistence adapter; hybrid ranking remains in the retrieval service."""

    def __init__(
        self, url: str, collection_name: str, embedding_provider: EmbeddingProvider
    ) -> None:
        from qdrant_client import QdrantClient

        self.client = QdrantClient(url=url)
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider

    def ensure_collection(self, dimension: int) -> None:
        from qdrant_client.http import models

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        from qdrant_client.http import models

        self.ensure_collection(len(self.embedding_provider.embed("dimension probe")))
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),
                    vector=self.embedding_provider.embed(chunk.content),
                    payload=chunk.model_dump(),
                )
                for chunk in chunks
            ],
        )
        return len(chunks)
