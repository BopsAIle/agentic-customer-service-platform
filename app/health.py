from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ComponentHealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    NOT_PROBED = "not_probed"


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    name: str
    status: ComponentHealthStatus
    detail: str


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    overall_ready: bool
    components: tuple[RuntimeHealthComponent, ...]

    def component(self, name: str) -> RuntimeHealthComponent:
        return next(item for item in self.components if item.name == name)


class RuntimeHealthRuntime(Protocol):
    settings: Settings

    def is_ready(self) -> bool: ...

    def readiness_category(self) -> str: ...


class RuntimeHealthCheckpoint(Protocol):
    @property
    def backend(self) -> Any: ...

    def is_ready(self) -> bool: ...


class RuntimeHealthService:
    """Request-scoped, observational health checks shared by readiness and operator health."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def snapshot(
        self,
        *,
        session: Session,
        checkpoint_provider: RuntimeHealthCheckpoint,
        runtime: RuntimeHealthRuntime,
        accepting_requests: bool,
    ) -> RuntimeHealthSnapshot:
        lifecycle = RuntimeHealthComponent(
            name="lifecycle",
            status=(
                ComponentHealthStatus.HEALTHY
                if accepting_requests
                else ComponentHealthStatus.UNAVAILABLE
            ),
            detail=(
                "Backend accepting requests"
                if accepting_requests
                else "Backend is not accepting requests"
            ),
        )
        database = self._database(session)
        checkpoint = self._checkpoint(checkpoint_provider)
        retrieval = self._retrieval(runtime)
        llm = self._llm()
        memory = self._memory()
        components = (lifecycle, database, checkpoint, retrieval, llm, memory)
        required = (lifecycle, database, checkpoint, retrieval)
        return RuntimeHealthSnapshot(
            overall_ready=all(item.status == ComponentHealthStatus.HEALTHY for item in required),
            components=components,
        )

    def _database(self, session: Session) -> RuntimeHealthComponent:
        try:
            session.execute(text("SELECT 1"))
        except Exception as error:
            logger.warning(
                "Runtime database health check failed.",
                extra={"health_component": "database", "health_error_type": type(error).__name__},
            )
            return RuntimeHealthComponent(
                name="database",
                status=ComponentHealthStatus.UNAVAILABLE,
                detail="PostgreSQL unavailable",
            )
        return RuntimeHealthComponent(
            name="database",
            status=ComponentHealthStatus.HEALTHY,
            detail="PostgreSQL reachable",
        )

    def _checkpoint(self, provider: RuntimeHealthCheckpoint) -> RuntimeHealthComponent:
        try:
            ready = provider.is_ready()
        except Exception as error:
            logger.warning(
                "Runtime checkpoint health check failed.",
                extra={
                    "health_component": "checkpoint",
                    "health_error_type": type(error).__name__,
                },
            )
            ready = False
        if not ready:
            return RuntimeHealthComponent(
                name="checkpoint",
                status=ComponentHealthStatus.UNAVAILABLE,
                detail="Checkpoint persistence unavailable",
            )
        backend = getattr(getattr(provider, "backend", None), "value", "durable")
        return RuntimeHealthComponent(
            name="checkpoint",
            status=ComponentHealthStatus.HEALTHY,
            detail=f"{str(backend).capitalize()} checkpoint persistence reachable",
        )

    def _retrieval(self, runtime: RuntimeHealthRuntime) -> RuntimeHealthComponent:
        backend = str(getattr(getattr(runtime, "settings", self.settings), "rag_backend", "qdrant"))
        try:
            ready = runtime.is_ready()
        except Exception as error:
            logger.warning(
                "Runtime retrieval health check failed.",
                extra={"health_component": "retrieval", "health_error_type": type(error).__name__},
            )
            return RuntimeHealthComponent(
                name="retriever",
                status=ComponentHealthStatus.UNAVAILABLE,
                detail="Retrieval backend unavailable",
            )

        if backend.casefold() == "local":
            return RuntimeHealthComponent(
                name="retriever",
                status=(
                    ComponentHealthStatus.HEALTHY if ready else ComponentHealthStatus.UNAVAILABLE
                ),
                detail=(
                    "Local retrieval backend usable"
                    if ready
                    else "Local retrieval backend unavailable"
                ),
            )

        if ready:
            return RuntimeHealthComponent(
                name="retriever",
                status=ComponentHealthStatus.HEALTHY,
                detail="Qdrant active snapshot compatible",
            )

        category = self._readiness_category(runtime)
        if category in {"qdrant_unreachable", "collection_missing"}:
            status = ComponentHealthStatus.UNAVAILABLE
            detail = "Qdrant unavailable"
        else:
            status = ComponentHealthStatus.INCOMPATIBLE
            detail = "Qdrant active snapshot incompatible"
        return RuntimeHealthComponent(name="retriever", status=status, detail=detail)

    @staticmethod
    def _readiness_category(runtime: RuntimeHealthRuntime) -> str:
        try:
            return str(runtime.readiness_category()).casefold()
        except (AttributeError, TypeError, ValueError):
            return "not_ready"

    def _llm(self) -> RuntimeHealthComponent:
        if (
            not self.settings.llm_provider
            or not self.settings.llm_model
            or not self.settings.llm_base_url
        ):
            return RuntimeHealthComponent(
                name="llm",
                status=ComponentHealthStatus.NOT_CONFIGURED,
                detail="LLM provider is not configured",
            )
        return RuntimeHealthComponent(
            name="llm",
            status=ComponentHealthStatus.NOT_PROBED,
            detail="LLM provider configured; availability not actively probed",
        )

    def _memory(self) -> RuntimeHealthComponent:
        if not self.settings.memory_enabled:
            return RuntimeHealthComponent(
                name="memory",
                status=ComponentHealthStatus.NOT_CONFIGURED,
                detail="Persistent memory is disabled",
            )
        return RuntimeHealthComponent(
            name="memory",
            status=ComponentHealthStatus.CONFIGURED,
            detail="Persistent memory configured; operation not independently probed",
        )
