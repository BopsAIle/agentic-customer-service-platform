from pathlib import Path

import app as app_package
from app.core.config import get_settings
from app.rag.embeddings import build_embedding_provider
from app.rag.ingestion.chunking import chunk_document
from app.rag.ingestion.loader import load_markdown_documents
from app.rag.storage.qdrant import QdrantKnowledgeStore


def main() -> None:
    settings = get_settings()
    package_file = app_package.__file__
    if package_file is None:
        raise RuntimeError("Application package location is unavailable.")
    documents = load_markdown_documents(Path(package_file).parent / "knowledge")
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, settings.rag_chunk_size)
    ]
    store = QdrantKnowledgeStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        build_embedding_provider(settings),
        timeout_seconds=settings.qdrant_timeout_seconds,
    )
    try:
        count = store.upsert(chunks)
    finally:
        store.close()
    print(
        f"Ingested {count} chunks into {settings.qdrant_collection} "
        f"with {settings.embedding_provider} embeddings."
    )


if __name__ == "__main__":
    main()
