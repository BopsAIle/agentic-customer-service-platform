import asyncio
import importlib
from collections.abc import Generator
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
