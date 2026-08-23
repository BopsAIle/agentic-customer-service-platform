import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.health import RuntimeHealthService
from app.observability.metrics import get_operational_summary
from app.persistence.checkpoint import CheckpointProvider
from app.schemas.health import (
    HealthDetailsResponse,
    HealthResponse,
    OperationalMetricsResponse,
    ReadinessResponse,
)

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process liveness only; dependency failures must not trigger restarts."""

    return HealthResponse()


@router.get("/health/details", response_model=HealthDetailsResponse)
def health_details(
    request: Request,
    session: Session = Depends(get_db),
) -> HealthDetailsResponse:
    """Return bounded operator diagnostics without secrets or request data."""

    settings = get_settings()
    snapshot = RuntimeHealthService(settings).operational_snapshot(
        session=session,
        checkpoint_provider=request.app.state.checkpoint_provider,
        runtime=request.app.state.agent_runtime,
        accepting_requests=getattr(request.app.state, "accepting_requests", False),
    )
    latencies = [item.latency_ms or 0.0 for item in snapshot.dependencies]
    summary = get_operational_summary()
    return HealthDetailsResponse(
        status=snapshot.status,
        version=snapshot.version,
        deployment_id=snapshot.deployment_id,
        dependencies=[
            {
                "name": item.name,
                "status": item.status.value,
                "latency_ms": round(item.latency_ms, 3) if item.latency_ms is not None else None,
                "detail": item.detail,
            }
            for item in snapshot.dependencies
        ],
        latency_summary={
            "total_ms": round(snapshot.total_latency_ms, 3),
            "max_dependency_ms": round(max(latencies, default=0.0), 3),
            "dependency_count": float(len(snapshot.dependencies)),
        },
        metrics=OperationalMetricsResponse(
            request_count=summary.request_count,
            error_rate=round(summary.error_rate, 6),
            average_duration_ms=round(summary.average_duration_ms, 3),
            retry_count=summary.retry_count,
            retry_exhausted_count=summary.retry_exhausted_count,
            circuit_open_count=summary.circuit_open_count,
        ),
    )


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> ReadinessResponse:
    """Return a bounded dependency-readiness result without exposing internals."""

    checkpoint_provider: CheckpointProvider = request.app.state.checkpoint_provider
    runtime = request.app.state.agent_runtime
    snapshot = RuntimeHealthService(get_settings()).snapshot(
        session=session,
        checkpoint_provider=checkpoint_provider,
        runtime=runtime,
        accepting_requests=getattr(request.app.state, "accepting_requests", False),
    )
    if not snapshot.overall_ready:
        failed_components = [
            item.name
            for item in snapshot.components
            if item.name in {"lifecycle", "database", "checkpoint", "retriever"}
            and item.status != "healthy"
        ]
        return _not_ready(response, failed_components[0] if failed_components else "runtime")
    return ReadinessResponse(status="ready")


def _not_ready(response: Response, component: str) -> ReadinessResponse:
    logger.warning(
        "Application readiness check failed.",
        extra={"readiness_status": "not_ready", "readiness_component": component},
    )
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="not_ready")
