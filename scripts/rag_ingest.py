from pathlib import Path

from app.core.config import get_settings
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.ingestion.chunking import chunk_document
from app.rag.ingestion.loader import load_markdown_documents
from app.rag.storage.qdrant import QdrantKnowledgeStore


def main() -> None:
    settings = get_settings()
    documents = load_markdown_documents(Path(__file__).parents[1] / "app" / "knowledge")
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, settings.rag_chunk_size)
    ]
    store = QdrantKnowledgeStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        DeterministicEmbeddingProvider(),
        timeout_seconds=settings.qdrant_timeout_seconds,
    )
    count = store.upsert(chunks)
    print(f"Ingested {count} deterministic chunks into {settings.qdrant_collection}.")


if __name__ == "__main__":
    main()
