.PHONY: sync dev up down test lint typecheck migrate seed rag-ingest rag-reset eval eval-safety eval-resilience eval-report eval-baseline observability-up observability-down frontend-install frontend-dev frontend-build frontend-test frontend-typecheck frontend-lint ci-backend ci-frontend security-audit docker-validate e2e-smoke

sync:
	uv sync --frozen

dev:
	uv run --frozen uvicorn app.main:app --reload

up:
	docker compose up --build -d

down:
	docker compose down

test:
	uv run --frozen pytest

lint:
	uv run --frozen ruff check . && uv run --frozen ruff format --check .

typecheck:
	uv run --frozen mypy app tests evaluation scripts

migrate:
	uv run --frozen alembic upgrade head

seed:
	uv run --frozen python -m scripts.seed

rag-ingest:
	uv run --frozen python -m scripts.rag_ingest

rag-reset:
	uv run --frozen python -c "from app.core.config import get_settings; from app.rag.embeddings import DeterministicEmbeddingProvider; from app.rag.storage.qdrant import QdrantKnowledgeStore; s=get_settings(); c=QdrantKnowledgeStore(s.qdrant_url, s.qdrant_collection, DeterministicEmbeddingProvider()); c.client.delete_collection(s.qdrant_collection) if c.client.collection_exists(s.qdrant_collection) else None"

eval:
	uv run --frozen python -m evaluation.runner

eval-safety:
	uv run --frozen python -m evaluation.runner --safety

eval-resilience:
	uv run --frozen python -m evaluation.runner --resilience

eval-report:
	uv run --frozen python -m evaluation.runner

eval-baseline:
	uv run --frozen python -m evaluation.runner --save-baseline

observability-up:
	docker compose up --build -d

observability-down:
	docker compose down

frontend-install:
	cd frontend && npm ci

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-test:
	cd frontend && npm test

frontend-typecheck:
	cd frontend && npm run typecheck

frontend-lint:
	cd frontend && npm run lint

ci-backend: sync lint typecheck test

ci-frontend: frontend-install frontend-typecheck frontend-lint frontend-test frontend-build

security-audit: sync frontend-install
	uv run --frozen pip-audit
	cd frontend && npm audit --audit-level=high

docker-validate:
	docker compose config --quiet
	docker build --tag customer-service-backend:local .
	docker build --tag customer-service-frontend:local frontend

e2e-smoke:
	python3 scripts/e2e_authenticated_smoke.py
