import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRuntime
from app.core.database import get_db
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

    if not getattr(request.app.state, "accepting_requests", False):
        return _not_ready(response, "lifecycle")
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return _not_ready(response, "database")

    checkpoint_provider: CheckpointProvider = request.app.state.checkpoint_provider
    if not checkpoint_provider.is_ready():
        return _not_ready(response, "checkpoint")

    runtime: AgentRuntime = request.app.state.agent_runtime
    try:
        knowledge_ready = runtime.is_ready()
    except Exception:
        return _not_ready(response, "knowledge")
    if not knowledge_ready:
        return _not_ready(response, "knowledge")
    return ReadinessResponse(status="ready")


def _not_ready(response: Response, component: str) -> ReadinessResponse:
    logger.warning(
        "Application readiness check failed.",
        extra={"readiness_status": "not_ready", "readiness_component": component},
    )
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="not_ready")
