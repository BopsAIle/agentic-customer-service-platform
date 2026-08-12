from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.rag.embeddings import EmbeddingProvider
from app.rag.retrieval.lexical import (
    LEXICAL_METADATA_KEY,
    LEXICAL_SCHEMA_VERSION,
    LEXICAL_VECTOR_NAME,
    LexicalIndex,
    build_lexical_index,
)
from app.rag.schemas import DocumentChunk

QDRANT_DENSE_DISTANCE = "Cosine"
SNAPSHOT_METADATA_KEY = "knowledge_snapshot"
KNOWLEDGE_SCHEMA_VERSION = 2
CHUNKING_VERSION = 1
SNAPSHOT_UPSERT_BATCH_SIZE = 128


@dataclass(frozen=True)
class KnowledgeSnapshot:
    snapshot_id: str
    collection_name: str
    corpus_hash: str
    chunk_count: int
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    lexical_index_hash: str
    created_at: str


def build_dense_vector_params(dimension: int) -> Any:
    """Build the one unnamed dense-vector schema used by snapshots and readiness."""

    from qdrant_client.http import models

    return models.VectorParams(size=dimension, distance=models.Distance.COSINE)


def build_sparse_vector_params() -> Any:
    """Build the named sparse index used by production lexical retrieval."""

    from qdrant_client.http import models

    return models.SparseVectorParams(index=models.SparseIndexParams())


class QdrantKnowledgeStore:
    """Build immutable Qdrant corpus snapshots and atomically activate their alias."""

    def __init__(
        self,
        url: str,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        *,
        timeout_seconds: float = 10.0,
        client: Any | None = None,
        embedding_model: str | None = None,
        schema_version: int = KNOWLEDGE_SCHEMA_VERSION,
        chunking_version: int = CHUNKING_VERSION,
    ) -> None:
        if client is None:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=url, timeout=_native_timeout(timeout_seconds))
        self.client = client
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.embedding_model = str(
            embedding_model
            or getattr(
                embedding_provider, "model", f"{embedding_provider.provider_type}-deterministic"
            )
        )
        self.schema_version = schema_version
        self.chunking_version = chunking_version
        self.timeout_seconds = timeout_seconds

    def upsert(self, chunks: Sequence[DocumentChunk]) -> int:
        """Compatibility entry point: always builds and activates a complete snapshot."""

        if self._physical_collection_exists_without_alias():
            raise RuntimeError(
                "Qdrant collection is not production hybrid and exists without the managed "
                "logical alias; refusing to mutate "
                "a legacy or operator-managed collection. Build a fresh snapshot instead."
            )
        snapshot = self.build_snapshot(chunks)
        return snapshot.chunk_count

    def build_snapshot(
        self,
        chunks: Sequence[DocumentChunk],
        *,
        corpus_version: str | None = None,
        activate: bool = True,
    ) -> KnowledgeSnapshot:
        canonical_chunks = _canonical_chunks(chunks)
        if not canonical_chunks:
            raise ValueError("At least one knowledge chunk is required for a snapshot.")
        if len({chunk.chunk_id for chunk in canonical_chunks}) != len(canonical_chunks):
            raise ValueError("Knowledge snapshot contains duplicate chunk IDs.")

        corpus_hash = _corpus_hash(canonical_chunks)
        snapshot_id = corpus_version or corpus_hash[:16]
        if not _safe_snapshot_id(snapshot_id):
            raise ValueError("Corpus version contains unsupported collection-name characters.")
        physical_name = f"{self.collection_name}_v_{snapshot_id}"
        vectors = self.embedding_provider.embed_documents(
            [chunk.content for chunk in canonical_chunks]
        )
        dimension = _validate_vectors(vectors, self.embedding_provider)
        lexical_index = build_lexical_index(canonical_chunks)
        lexical_metadata = lexical_index.to_metadata()
        lexical_index_hash = _metadata_hash(lexical_metadata)
        created_at = datetime.now(UTC).isoformat()
        provenance = {
            "snapshot_id": snapshot_id,
            "corpus_hash": corpus_hash,
            "corpus_version": corpus_version or corpus_hash,
            "chunk_count": len(canonical_chunks),
            "embedding_provider": self.embedding_provider.provider_type,
            "embedding_model": self.embedding_model,
            "embedding_dimension": dimension,
            "lexical_index_version": LEXICAL_SCHEMA_VERSION,
            "lexical_index_hash": lexical_index_hash,
            "schema_version": self.schema_version,
            "chunking_version": self.chunking_version,
            "created_at": created_at,
        }

        if self.client.collection_exists(physical_name):
            existing = _collection_metadata(self.client.get_collection(physical_name))
            existing_provenance = existing.get(SNAPSHOT_METADATA_KEY)
            if not isinstance(existing_provenance, dict) or not _same_provenance(
                existing_provenance, provenance
            ):
                raise RuntimeError(
                    "A physical snapshot collection already exists with incompatible provenance."
                )
            provenance = existing_provenance
            created_at = str(existing_provenance.get("created_at", created_at))
        else:
            from qdrant_client.http import models

            self.client.create_collection(
                collection_name=physical_name,
                vectors_config=build_dense_vector_params(dimension),
                sparse_vectors_config={LEXICAL_VECTOR_NAME: build_sparse_vector_params()},
                metadata={
                    LEXICAL_METADATA_KEY: lexical_metadata,
                    SNAPSHOT_METADATA_KEY: provenance,
                },
                timeout=_native_timeout(self.timeout_seconds),
            )
            points = [
                _point(
                    models=models,
                    chunk=chunk,
                    vector=vector,
                    lexical_index=lexical_index,
                )
                for chunk, vector in zip(canonical_chunks, vectors, strict=True)
            ]
            for offset in range(0, len(points), SNAPSHOT_UPSERT_BATCH_SIZE):
                self.client.upsert(
                    collection_name=physical_name,
                    points=points[offset : offset + SNAPSHOT_UPSERT_BATCH_SIZE],
                    timeout=_native_timeout(self.timeout_seconds),
                )

        snapshot = KnowledgeSnapshot(
            snapshot_id=snapshot_id,
            collection_name=physical_name,
            corpus_hash=corpus_hash,
            chunk_count=len(canonical_chunks),
            embedding_provider=self.embedding_provider.provider_type,
            embedding_model=self.embedding_model,
            embedding_dimension=dimension,
            lexical_index_hash=lexical_index_hash,
            created_at=created_at,
        )
        self.validate_snapshot(snapshot)
        if activate:
            self.activate(snapshot.collection_name)
        return snapshot

    def validate_snapshot(self, snapshot: KnowledgeSnapshot) -> None:
        collection = self.client.get_collection(snapshot.collection_name)
        metadata = _collection_metadata(collection)
        provenance = metadata.get(SNAPSHOT_METADATA_KEY)
        if (
            not isinstance(provenance, dict)
            or provenance.get("corpus_hash") != snapshot.corpus_hash
        ):
            raise RuntimeError("Qdrant snapshot provenance validation failed.")
        lexical_metadata = metadata.get(LEXICAL_METADATA_KEY)
        if (
            not isinstance(lexical_metadata, dict)
            or _metadata_hash(lexical_metadata) != snapshot.lexical_index_hash
        ):
            raise RuntimeError("Qdrant snapshot lexical provenance validation failed.")
        expected_provenance = {
            "embedding_provider": snapshot.embedding_provider,
            "embedding_model": snapshot.embedding_model,
            "embedding_dimension": snapshot.embedding_dimension,
            "lexical_index_version": LEXICAL_SCHEMA_VERSION,
            "lexical_index_hash": snapshot.lexical_index_hash,
            "schema_version": self.schema_version,
            "chunking_version": self.chunking_version,
            "chunk_count": snapshot.chunk_count,
        }
        if any(provenance.get(key) != value for key, value in expected_provenance.items()):
            raise RuntimeError("Qdrant snapshot provenance validation failed.")
        point_count = _field(collection, "points_count")
        if not isinstance(point_count, int) or point_count != snapshot.chunk_count:
            raise RuntimeError("Qdrant snapshot point-count validation failed.")
        params = _field(_field(collection, "config"), "params")
        vectors = _field(params, "vectors")
        sparse_vectors = _field(params, "sparse_vectors")
        sparse_config = (
            sparse_vectors.get(LEXICAL_VECTOR_NAME) if isinstance(sparse_vectors, dict) else None
        )
        if (
            isinstance(vectors, dict)
            or _field(vectors, "size") != snapshot.embedding_dimension
            or _enum_value(_field(vectors, "distance")) != QDRANT_DENSE_DISTANCE
            or sparse_config is None
            or _field(sparse_config, "index") is None
        ):
            raise RuntimeError("Qdrant snapshot schema validation failed.")

    def activate(self, physical_collection: str) -> None:
        """Atomically switch the logical alias, preserving the prior target on failure."""

        from qdrant_client.http import models

        if not self.client.collection_exists(physical_collection):
            raise ValueError("Cannot activate a missing Qdrant snapshot collection.")
        current = _alias_target(self.client, self.collection_name)
        operations: list[Any] = []
        if current is not None:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.collection_name)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=physical_collection,
                    alias_name=self.collection_name,
                )
            )
        )
        self.client.update_collection_aliases(
            operations,
            timeout=_native_timeout(self.timeout_seconds),
        )

    def rollback(self, snapshot_collection: str) -> None:
        """Switch to an existing validated snapshot without rebuilding it."""

        metadata = _collection_metadata(self.client.get_collection(snapshot_collection))
        provenance = metadata.get(SNAPSHOT_METADATA_KEY)
        if not isinstance(provenance, dict):
            raise ValueError("Rollback target is not a managed knowledge snapshot.")
        try:
            snapshot = KnowledgeSnapshot(
                snapshot_id=str(provenance["snapshot_id"]),
                collection_name=snapshot_collection,
                corpus_hash=str(provenance["corpus_hash"]),
                chunk_count=int(provenance["chunk_count"]),
                embedding_provider=str(provenance["embedding_provider"]),
                embedding_model=str(provenance["embedding_model"]),
                embedding_dimension=int(provenance["embedding_dimension"]),
                lexical_index_hash=str(provenance["lexical_index_hash"]),
                created_at=str(provenance["created_at"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Rollback target has invalid snapshot provenance.") from error
        self.validate_snapshot(snapshot)
        self.activate(snapshot_collection)

    def list_snapshots(self) -> list[dict[str, object]]:
        collections = self.client.get_collections().collections
        active = _alias_target(self.client, self.collection_name)
        snapshots: list[dict[str, object]] = []
        for item in collections:
            name = str(_field(item, "name"))
            if not name.startswith(f"{self.collection_name}_v_"):
                continue
            info = self.client.get_collection(name)
            metadata = _collection_metadata(info).get(SNAPSHOT_METADATA_KEY, {})
            if not isinstance(metadata, dict):
                continue
            snapshots.append(
                {
                    "collection_name": name,
                    "active": name == active,
                    "points_count": _field(info, "points_count"),
                    **metadata,
                }
            )
        return sorted(snapshots, key=lambda value: str(value.get("created_at", "")))

    def close(self) -> None:
        self.client.close()

    def _physical_collection_exists_without_alias(self) -> bool:
        return (
            self.client.collection_exists(self.collection_name)
            and _alias_target(self.client, self.collection_name) is None
        )


def _canonical_chunks(chunks: Sequence[DocumentChunk]) -> list[DocumentChunk]:
    return sorted(chunks, key=lambda chunk: chunk.chunk_id)


def _corpus_hash(chunks: Sequence[DocumentChunk]) -> str:
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _metadata_hash(metadata: dict[str, object]) -> str:
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _same_provenance(first: dict[str, object], second: dict[str, object]) -> bool:
    return {key: value for key, value in first.items() if key != "created_at"} == {
        key: value for key, value in second.items() if key != "created_at"
    }


def _safe_snapshot_id(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "-_" for character in value)


def _validate_vectors(vectors: Sequence[Sequence[float]], provider: EmbeddingProvider) -> int:
    dimension = getattr(provider, "dimension", None)
    if not vectors:
        raise ValueError("Embedding provider returned no vectors.")
    actual = len(vectors[0])
    if dimension is not None and actual != dimension:
        raise ValueError("Embedding provider returned an unexpected vector dimension.")
    if any(len(vector) != actual for vector in vectors):
        raise ValueError("Embedding provider returned inconsistent vector dimensions.")
    return actual


def _native_timeout(seconds: float) -> int:
    """Qdrant's HTTP API accepts whole-second server deadlines only."""

    return max(1, int(seconds))


def _field(value: object, name: str) -> object | None:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _collection_metadata(collection: object) -> dict[str, object]:
    metadata = _field(_field(collection, "config"), "metadata")
    return metadata if isinstance(metadata, dict) else {}


def _alias_target(client: Any, alias_name: str) -> str | None:
    get_aliases = getattr(client, "get_aliases", None)
    if not callable(get_aliases):
        return None
    response = get_aliases()
    for alias in getattr(response, "aliases", []):
        if _field(alias, "alias_name") == alias_name:
            target = _field(alias, "collection_name")
            return str(target) if target is not None else None
    return None


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
