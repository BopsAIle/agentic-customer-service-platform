from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import Settings
from app.observability.attributes import set_safe_attributes
from app.observability.metrics import configure_metrics

logger = logging.getLogger(__name__)
_tracer_provider: TracerProvider | None = None


def configure_observability(settings: Settings) -> None:
    global _tracer_provider
    if not settings.otel_enabled:
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    configure_metrics(metrics.get_meter_provider())


def shutdown_observability(timeout_millis: int = 5000) -> None:
    """Flush and close only the tracer provider owned by this application."""

    global _tracer_provider
    provider = _tracer_provider
    if provider is None:
        return
    try:
        provider.force_flush(timeout_millis=timeout_millis)
    except Exception as error:
        logger.warning(
            "Telemetry flush failed during shutdown.",
            extra={"telemetry_error_type": type(error).__name__},
        )
    finally:
        try:
            provider.shutdown()
        except Exception as error:
            logger.warning(
                "Telemetry provider shutdown failed.",
                extra={"telemetry_error_type": type(error).__name__},
            )
        _tracer_provider = None


def tracer(name: str = "agentic-customer-service-platform") -> trace.Tracer:
    return trace.get_tracer(name)


@contextmanager
def span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name) as active_span:
        if attributes:
            set_safe_attributes(active_span, attributes)
        yield active_span
