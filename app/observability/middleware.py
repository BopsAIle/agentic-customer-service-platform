from fastapi import FastAPI

from app.core.config import Settings


def instrument_fastapi(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
