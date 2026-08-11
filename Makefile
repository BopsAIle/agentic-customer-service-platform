.PHONY: dev up down test lint typecheck migrate seed rag-ingest rag-reset

dev:
	uv run uvicorn app.main:app --reload

up:
	docker compose up --build -d

down:
	docker compose down

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy app tests

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m scripts.seed

rag-ingest:
	uv run python -m scripts.rag_ingest

rag-reset:
	uv run python -c "from app.core.config import get_settings; from app.rag.embeddings import DeterministicEmbeddingProvider; from app.rag.storage.qdrant import QdrantKnowledgeStore; s=get_settings(); c=QdrantKnowledgeStore(s.qdrant_url, s.qdrant_collection, DeterministicEmbeddingProvider()); c.client.delete_collection(s.qdrant_collection) if c.client.collection_exists(s.qdrant_collection) else None"
