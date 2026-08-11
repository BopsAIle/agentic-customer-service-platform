from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.memory.service import MemoryService
from app.observability.metrics import configure_metrics

_SPAN_EXPORTER = InMemorySpanExporter()
_TRACER_PROVIDER = TracerProvider()
_TRACER_PROVIDER.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
_TRACER_CONFIGURED = False


@pytest.fixture
def telemetry() -> Iterator[tuple[InMemorySpanExporter, InMemoryMetricReader]]:
    global _TRACER_CONFIGURED
    if not _TRACER_CONFIGURED:
        trace.set_tracer_provider(_TRACER_PROVIDER)
        _TRACER_CONFIGURED = True
    _SPAN_EXPORTER.clear()
    metric_reader = InMemoryMetricReader()
    configure_metrics(MeterProvider(metric_readers=[metric_reader]))
    yield _SPAN_EXPORTER, metric_reader


def decision(
    intent: Intent,
    request_type: AgentRequestType,
    tool_name: str | None = None,
    arguments: dict[str, object] | None = None,
    *,
    requires_retrieval: bool = False,
    knowledge_query: str | None = None,
) -> StructuredDecision:
    return StructuredDecision(
        intent=intent,
        request_type=request_type,
        tool_name=tool_name,
        arguments=arguments or {},
        requires_retrieval=requires_retrieval,
        knowledge_query=knowledge_query,
        reason="observability test",
    )


def span_names(exporter: InMemorySpanExporter) -> set[str]:
    return {span.name for span in exporter.get_finished_spans()}


def span_attributes(exporter: InMemorySpanExporter) -> list[object]:
    return [
        value
        for span in exporter.get_finished_spans()
        for value in (span.attributes or {}).values()
    ]


def test_read_action_emits_root_and_tool_spans_without_sensitive_prompt(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, _ = telemetry
    message = "Look up order 2 with private customer details"
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LOOKUP,
                    AgentRequestType.READ_ACTION,
                    "get_order",
                    {"customer_id": 1, "order_id": 2},
                )
            ]
        )
    )
    runtime.run(
        conversation_id="otel-read",
        customer_id=1,
        message=message,
        session=db_session,
    )
    names = span_names(exporter)
    assert {
        "agent.run",
        "agent.understand_request",
        "llm.structured_decision",
        "tool.execute",
    } <= names
    assert message not in span_attributes(exporter)
    assert 2 not in span_attributes(exporter)


def test_knowledge_request_emits_rag_spans_without_chunk_content(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, _ = telemetry
    content = "Delivered orders may qualify for refund review."
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.REFUND_POLICY,
                    AgentRequestType.KNOWLEDGE_ONLY,
                    requires_retrieval=True,
                    knowledge_query="refund policy",
                )
            ]
        )
    )
    runtime.run(
        conversation_id="otel-rag",
        customer_id=1,
        message="What is the refund policy?",
        session=db_session,
    )
    names = span_names(exporter)
    assert {
        "agent.run",
        "rag.retrieve",
        "rag.embed_query",
        "rag.dense_search",
        "rag.sparse_search",
        "rag.fusion",
        "rag.rerank",
        "rag.context_build",
    } <= names
    assert content not in span_attributes(exporter)


def test_confirmation_and_failure_spans_record_bounded_outcomes(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, _ = telemetry
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_CANCEL,
                    AgentRequestType.WRITE_ACTION,
                    "cancel_order",
                    {"customer_id": 1, "order_id": 3},
                )
            ]
        )
    )
    runtime.run(
        conversation_id="otel-confirm",
        customer_id=1,
        message="Cancel order 3",
        session=db_session,
    )
    runtime.run(
        conversation_id="otel-confirm",
        customer_id=1,
        message="Yes",
        session=db_session,
    )
    names = span_names(exporter)
    assert {
        "confirmation.evaluate",
        "policy.evaluate",
        "policy.revalidate",
        "tool.execute",
    } <= names
    assert "confirmed" in span_attributes(exporter)


def test_metrics_reader_observes_tool_and_policy_counters(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, metric_reader = telemetry
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LOOKUP,
                    AgentRequestType.READ_ACTION,
                    "get_order",
                    {"customer_id": 1, "order_id": 1},
                )
            ]
        )
    )
    runtime.run(
        conversation_id="otel-metrics",
        customer_id=1,
        message="Look up order 1",
        session=db_session,
    )
    data = metric_reader.get_metrics_data()
    assert data is not None
    names = {
        metric.name
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assert {"agent_runs_total", "tool_calls_total", "policy_decisions_total"} <= names
    assert span_names(exporter)


def test_failed_tool_records_error_category_without_arguments(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, _ = telemetry
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LOOKUP,
                    AgentRequestType.READ_ACTION,
                    "get_order",
                    {"customer_id": 1, "order_id": 999},
                )
            ]
        )
    )
    runtime.run(
        conversation_id="otel-failure",
        customer_id=1,
        message="Look up an unavailable order",
        session=db_session,
    )
    tool_spans = [item for item in exporter.get_finished_spans() if item.name == "tool.execute"]
    assert tool_spans
    assert tool_spans[0].attributes is not None
    assert tool_spans[0].attributes.get("error.category") == "resource_not_found"
    assert 999 not in span_attributes(exporter)


def test_memory_spans_include_outcomes_but_not_memory_content(
    db_session: Session, telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    exporter, metric_reader = telemetry
    content = "The customer prefers a private channel that must not be telemetry."
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                StructuredDecision(
                    intent=Intent.MEMORY_REMEMBER,
                    request_type=AgentRequestType.MEMORY_ACTION,
                    reason="memory privacy",
                )
            ]
        ),
        memory_service=MemoryService(),
    )
    runtime.run(
        conversation_id="otel-memory",
        customer_id=1,
        message="Remember that I prefer email updates.",
        session=db_session,
    )
    names = span_names(exporter)
    assert {"memory.retrieve", "memory.evaluate_candidate", "agent.run"} <= names
    assert content not in span_attributes(exporter)
    assert "The customer prefers email updates." not in span_attributes(exporter)
    data = metric_reader.get_metrics_data()
    assert data is not None
