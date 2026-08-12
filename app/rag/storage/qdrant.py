from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.rag.embeddings import EmbeddingProvider
from app.rag.retrieval.lexical import (
    LEXICAL_METADATA_KEY,
    LEXICAL_VECTOR_NAME,
    LexicalIndex,
    build_lexical_index,
)
from app.rag.schemas import DocumentChunk

QDRANT_DENSE_DISTANCE = "Cosine"


def build_dense_vector_params(dimension: int) -> Any:
    """Build the one unnamed dense-vector schema used by ingestion and readiness."""

    from qdrant_client.http import models

    return models.VectorParams(size=dimension, distance=models.Distance.COSINE)


def build_sparse_vector_params() -> Any:
    """Build the named sparse index used by production lexical retrieval."""

    from qdrant_client.http import models

    return models.SparseVectorParams(index=models.SparseIndexParams())


class QdrantKnowledgeStore:
    """Persist dense and deterministic lexical vectors for Qdrant hybrid retrieval."""

    def __init__(
        self,
        url: str,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        *,
        timeout_seconds: float = 10.0,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=url, timeout=_native_timeout(timeout_seconds))
        self.client = client
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.timeout_seconds = timeout_seconds

    def ensure_collection(self, dimension: int, lexical_index: LexicalIndex) -> None:
        exists = self.client.collection_exists(self.collection_name)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=build_dense_vector_params(dimension),
                sparse_vectors_config={LEXICAL_VECTOR_NAME: build_sparse_vector_params()},
                metadata={LEXICAL_METADATA_KEY: lexical_index.to_metadata()},
                timeout=_native_timeout(self.timeout_seconds),
            )
            return

        collection = self.client.get_collection(self.collection_name)
        params = _field(_field(collection, "config"), "params")
        vectors = _field(params, "vectors")
        sparse_vectors = _field(params, "sparse_vectors")
        sparse_config = (
            sparse_vectors.get(LEXICAL_VECTOR_NAME) if isinstance(sparse_vectors, dict) else None
        )
        if (
            isinstance(vectors, dict)
            or _field(vectors, "size") != dimension
            or _enum_value(_field(vectors, "distance")) != QDRANT_DENSE_DISTANCE
            or sparse_config is None
            or _field(sparse_config, "index") is None
        ):
            raise RuntimeError(
                "Qdrant collection schema is not production hybrid; re-ingest into a "
                "fresh compatible collection before serving traffic."
            )
        self.client.update_collection(
            collection_name=self.collection_name,
            metadata={LEXICAL_METADATA_KEY: lexical_index.to_metadata()},
            timeout=_native_timeout(self.timeout_seconds),
        )

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        from qdrant_client.http import models

        vectors = self.embedding_provider.embed_documents([chunk.content for chunk in chunks])
        dimension = (
            len(vectors[0]) if vectors else len(self.embedding_provider.embed_query("probe"))
        )
        lexical_index = build_lexical_index(chunks)
        self.ensure_collection(dimension, lexical_index)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                _point(
                    models=models,
                    chunk=chunk,
                    vector=vector,
                    lexical_index=lexical_index,
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


def _field(value: object, name: str) -> object | None:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _point(
    *, models: Any, chunk: DocumentChunk, vector: list[float], lexical_index: LexicalIndex
) -> Any:
    indices, values = lexical_index.encode(chunk.content)
    return models.PointStruct(
        id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),
        vector={
            "": vector,
            LEXICAL_VECTOR_NAME: models.SparseVector(indices=indices, values=values),
        },
        payload=chunk.model_dump(),
    )
