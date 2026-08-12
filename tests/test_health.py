import asyncio
import importlib
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.core.database import get_db
from app.main import app
from app.persistence.checkpoint import CheckpointBackend

main_module = importlib.import_module("app.main")


class FailingSession:
    def execute(self, statement: object) -> None:
        del statement
        raise ConnectionError("database unavailable")


class UnreadyCheckpointProvider:
    def is_ready(self) -> bool:
        return False


class UnreadyRuntime:
    def is_ready(self) -> bool:
        return False


class QdrantRuntime:
    settings = SimpleNamespace(rag_backend="qdrant")

    def __init__(self, ready: bool, category: str) -> None:
        self.ready = ready
        self.category = category

    def is_ready(self) -> bool:
        return self.ready

    def readiness_category(self) -> str:
        return self.category


class ObservableQdrantRuntime(QdrantRuntime):
    def __init__(self) -> None:
        super().__init__(True, "ready")
        self.readiness_checks = 0
        self.mutation_calls = 0

    def is_ready(self) -> bool:
        self.readiness_checks += 1
        return super().is_ready()

    def create_collection(self) -> None:
        self.mutation_calls += 1

    def delete_collection(self) -> None:
        self.mutation_calls += 1

    def activate_alias(self) -> None:
        self.mutation_calls += 1


def test_liveness_does_not_depend_on_database(client: TestClient) -> None:
    original = app.dependency_overrides[get_db]

    def failing_database() -> Generator[FailingSession, None, None]:
        yield FailingSession()

    app.dependency_overrides[get_db] = failing_database
    try:
        health = client.get("/health")
        readiness = client.get("/ready")
    finally:
        app.dependency_overrides[get_db] = original

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}


def test_readiness_hides_checkpoint_failure_details(client: TestClient) -> None:
    original = app.state.checkpoint_provider
    app.state.checkpoint_provider = UnreadyCheckpointProvider()
    try:
        response = client.get("/ready")
    finally:
        app.state.checkpoint_provider = original

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "checkpoint" not in response.text


def test_readiness_hides_knowledge_failure_details(client: TestClient) -> None:
    original = app.state.agent_runtime
    app.state.agent_runtime = UnreadyRuntime()
    try:
        response = client.get("/ready")
    finally:
        app.state.agent_runtime = original

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "knowledge" not in response.text


def test_system_health_projects_database_failure_without_raw_details(
    client: TestClient,
) -> None:
    original = app.dependency_overrides[get_db]

    def failing_database() -> Generator[FailingSession, None, None]:
        yield FailingSession()

    app.dependency_overrides[get_db] = failing_database
    try:
        response = client.get("/ui/system-health")
    finally:
        app.dependency_overrides[get_db] = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_ready"
    database = next(item for item in payload["components"] if item["name"] == "database")
    assert database == {
        "name": "database",
        "status": "unavailable",
        "detail": "PostgreSQL unavailable",
    }
    assert "database unavailable" not in response.text.casefold()


def test_readiness_and_system_health_share_qdrant_unavailable_semantics(
    client: TestClient,
) -> None:
    original = app.state.agent_runtime
    app.state.agent_runtime = QdrantRuntime(False, "qdrant_unreachable")
    try:
        readiness = client.get("/ready")
        health = client.get("/ui/system-health")
    finally:
        app.state.agent_runtime = original

    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}
    payload = health.json()
    assert payload["status"] == "not_ready"
    retrieval = next(item for item in payload["components"] if item["name"] == "retriever")
    assert retrieval["status"] == "unavailable"
    assert retrieval["detail"] == "Qdrant unavailable"
    assert "qdrant_unreachable" not in health.text


def test_qdrant_provenance_mismatch_is_incompatible_not_healthy(
    client: TestClient,
) -> None:
    original = app.state.agent_runtime
    app.state.agent_runtime = QdrantRuntime(False, "provenance_mismatch")
    try:
        response = client.get("/ui/system-health")
    finally:
        app.state.agent_runtime = original

    retrieval = next(item for item in response.json()["components"] if item["name"] == "retriever")
    assert retrieval["status"] == "incompatible"
    assert retrieval["detail"] == "Qdrant active snapshot incompatible"


def test_health_checks_are_observational_and_share_the_readiness_boundary(
    client: TestClient,
) -> None:
    original = app.state.agent_runtime
    runtime = ObservableQdrantRuntime()
    app.state.agent_runtime = runtime
    try:
        readiness = client.get("/ready")
        health = client.get("/ui/system-health")
    finally:
        app.state.agent_runtime = original

    assert readiness.status_code == 200
    assert health.json()["status"] == "ready"
    assert runtime.readiness_checks == 2
    assert runtime.mutation_calls == 0


def test_local_retrieval_does_not_require_qdrant(client: TestClient) -> None:
    payload = client.get("/ui/system-health").json()
    retrieval = next(item for item in payload["components"] if item["name"] == "retriever")
    llm = next(item for item in payload["components"] if item["name"] == "llm")

    assert payload["status"] == "ready"
    assert retrieval["status"] == "healthy"
    assert retrieval["detail"] == "Local retrieval backend usable"
    assert llm["status"] == "not_probed"
    assert "not actively probed" in llm["detail"]


def test_checkpoint_failure_is_projected_without_changing_liveness(
    client: TestClient,
) -> None:
    original = app.state.checkpoint_provider
    app.state.checkpoint_provider = UnreadyCheckpointProvider()
    try:
        readiness = client.get("/ready")
        health = client.get("/ui/system-health")
    finally:
        app.state.checkpoint_provider = original

    assert readiness.status_code == 503
    assert health.json()["status"] == "not_ready"
    checkpoint = next(item for item in health.json()["components"] if item["name"] == "checkpoint")
    assert checkpoint["status"] == "unavailable"


def test_lifespan_closes_owned_resources_in_order(monkeypatch: Any) -> None:
    events: list[str] = []

    class CheckpointProvider:
        backend = CheckpointBackend.MEMORY
        checkpointer = MemorySaver()

        def initialize(self) -> None:
            events.append("checkpoint_initialize")

        def close(self) -> None:
            events.append("checkpoint_close")

    class Runtime:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            events.append("runtime_initialize")

        def close(self) -> None:
            events.append("runtime_close")

    class Engine:
        def dispose(self) -> None:
            events.append("database_close")

    monkeypatch.setattr(
        main_module,
        "build_checkpoint_provider",
        lambda _settings: CheckpointProvider(),
    )
    monkeypatch.setattr(main_module, "AgentRuntime", Runtime)
    monkeypatch.setattr(main_module, "engine", Engine())
    monkeypatch.setattr(
        main_module,
        "shutdown_observability",
        lambda: events.append("telemetry_close"),
    )

    application = FastAPI()

    async def exercise_lifespan() -> None:
        async with main_module.lifespan(application):
            assert application.state.accepting_requests is True
        assert application.state.accepting_requests is False

    asyncio.run(exercise_lifespan())

    assert events == [
        "checkpoint_initialize",
        "runtime_initialize",
        "runtime_close",
        "checkpoint_close",
        "database_close",
        "telemetry_close",
    ]
