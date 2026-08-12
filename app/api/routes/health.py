import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.health import RuntimeHealthService
from app.persistence.checkpoint import CheckpointProvider
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process liveness only; dependency failures must not trigger restarts."""

    return HealthResponse()


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
