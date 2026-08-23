from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
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


class OperationalHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DEPENDENCY_FAILURE = "dependency_failure"


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    name: str
    status: ComponentHealthStatus
    detail: str
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    overall_ready: bool
    components: tuple[RuntimeHealthComponent, ...]

    def component(self, name: str) -> RuntimeHealthComponent:
        return next(item for item in self.components if item.name == name)


@dataclass(frozen=True, slots=True)
class OperationalHealthSnapshot:
    status: OperationalHealthState
    dependencies: tuple[RuntimeHealthComponent, ...]
    total_latency_ms: float
    version: str
    deployment_id: str


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
        database = self._timed(lambda: self._database(session))
        checkpoint = self._timed(lambda: self._checkpoint(checkpoint_provider))
        retrieval = self._timed(lambda: self._retrieval(runtime))
        llm = self._timed(self._llm)
        memory = self._timed(self._memory)
        evidence = self._timed(self._evidence_store)
        authentication = self._timed(self._authentication)
        telemetry = self._timed(self._telemetry)
        components = (
            lifecycle,
            database,
            checkpoint,
            retrieval,
            llm,
            memory,
            evidence,
            authentication,
            telemetry,
        )
        required = (lifecycle, database, checkpoint, retrieval)
        return RuntimeHealthSnapshot(
            overall_ready=all(item.status == ComponentHealthStatus.HEALTHY for item in required),
            components=components,
        )

    def operational_snapshot(
        self,
        *,
        session: Session,
        checkpoint_provider: RuntimeHealthCheckpoint,
        runtime: RuntimeHealthRuntime,
        accepting_requests: bool,
    ) -> OperationalHealthSnapshot:
        started = time.perf_counter()
        runtime_snapshot = self.snapshot(
            session=session,
            checkpoint_provider=checkpoint_provider,
            runtime=runtime,
            accepting_requests=accepting_requests,
        )
        components = {item.name: item for item in runtime_snapshot.components}
        dependencies = tuple(
            components[name]
            for name in (
                "database",
                "retriever",
                "evidence_store",
                "authentication_provider",
                "llm",
                "opentelemetry",
            )
        )
        lifecycle_failed = components["lifecycle"].status != ComponentHealthStatus.HEALTHY
        required_dependency_failed = any(
            components[name].status != ComponentHealthStatus.HEALTHY
            for name in ("database", "checkpoint", "retriever")
        )
        optional_failed = any(
            item.status not in {ComponentHealthStatus.HEALTHY, ComponentHealthStatus.CONFIGURED}
            for item in dependencies[2:]
        )
        if lifecycle_failed:
            health_status = OperationalHealthState.UNAVAILABLE
        elif required_dependency_failed or any(
            item.status in {ComponentHealthStatus.UNAVAILABLE, ComponentHealthStatus.INCOMPATIBLE}
            for item in dependencies
        ):
            health_status = OperationalHealthState.DEPENDENCY_FAILURE
        elif optional_failed:
            health_status = OperationalHealthState.DEGRADED
        else:
            health_status = OperationalHealthState.HEALTHY
        return OperationalHealthSnapshot(
            status=health_status,
            dependencies=dependencies,
            total_latency_ms=(time.perf_counter() - started) * 1000,
            version=self.settings.service_version,
            deployment_id=self.settings.deployment_id,
        )

    @staticmethod
    def _timed(probe: Callable[[], RuntimeHealthComponent]) -> RuntimeHealthComponent:
        started = time.perf_counter()
        component = probe()
        return replace(component, latency_ms=(time.perf_counter() - started) * 1000)

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

    def _evidence_store(self) -> RuntimeHealthComponent:
        backend = self.settings.evidence_store_backend.casefold()
        if backend == "local":
            from pathlib import Path

            root = Path(self.settings.evidence_store_root)
            return RuntimeHealthComponent(
                name="evidence_store",
                status=(
                    ComponentHealthStatus.HEALTHY
                    if root.exists() and root.is_dir()
                    else ComponentHealthStatus.NOT_CONFIGURED
                ),
                detail=(
                    "Local evidence store configured"
                    if root.exists() and root.is_dir()
                    else "Local evidence store path is not available"
                ),
            )
        if backend == "s3" and self.settings.evidence_store_bucket:
            return RuntimeHealthComponent(
                name="evidence_store",
                status=ComponentHealthStatus.CONFIGURED,
                detail="S3-compatible evidence store configured; availability not actively probed",
            )
        return RuntimeHealthComponent(
            name="evidence_store",
            status=ComponentHealthStatus.NOT_CONFIGURED,
            detail="Evidence store is not configured",
        )

    def _authentication(self) -> RuntimeHealthComponent:
        configured = (
            self.settings.auth_mode.value == "oidc"
            and bool(self.settings.oidc_issuer and self.settings.oidc_audience)
        ) or self.settings.auth_mode.value in {"local_demo", "static", "disabled"}
        return RuntimeHealthComponent(
            name="authentication_provider",
            status=(
                ComponentHealthStatus.CONFIGURED
                if configured
                else ComponentHealthStatus.NOT_CONFIGURED
            ),
            detail=(
                "Authentication boundary configured; provider availability not actively probed"
                if configured
                else "Authentication provider configuration is incomplete"
            ),
        )

    def _telemetry(self) -> RuntimeHealthComponent:
        configured = bool(self.settings.otel_enabled and self.settings.otel_exporter_otlp_endpoint)
        return RuntimeHealthComponent(
            name="opentelemetry",
            status=(
                ComponentHealthStatus.CONFIGURED
                if configured
                else ComponentHealthStatus.NOT_CONFIGURED
            ),
            detail=(
                "OpenTelemetry pipeline configured; export availability not actively probed"
                if configured
                else "OpenTelemetry export is disabled"
            ),
        )
