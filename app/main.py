from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.runtime import AgentRuntime
from app.api.router import api_router
from app.core.config import get_settings
from app.observability.middleware import instrument_fastapi
from app.observability.tracing import configure_observability
from app.persistence.checkpoint import build_checkpoint_provider

settings = get_settings()
configure_observability(settings)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    checkpoint_provider = build_checkpoint_provider(settings)
    try:
        checkpoint_provider.initialize()
        application.state.checkpoint_provider = checkpoint_provider
        application.state.agent_runtime = AgentRuntime(
            checkpointer=checkpoint_provider.checkpointer,
            checkpoint_backend=checkpoint_provider.backend,
        )
        yield
    finally:
        checkpoint_provider.close()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
instrument_fastapi(app, settings)
app.include_router(api_router)
