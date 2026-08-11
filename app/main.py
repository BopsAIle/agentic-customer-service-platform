from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.observability.middleware import instrument_fastapi
from app.observability.tracing import configure_observability

settings = get_settings()
configure_observability(settings)
app = FastAPI(title=settings.app_name, debug=settings.debug)
instrument_fastapi(app, settings)
app.include_router(api_router)
