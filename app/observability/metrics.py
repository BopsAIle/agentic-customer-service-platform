from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics
from opentelemetry.metrics import Meter, MeterProvider


@dataclass(frozen=True, slots=True)
class ObservabilityMetrics:
    agent_runs_total: Any
    agent_run_duration_seconds: Any
    tool_calls_total: Any
    tool_call_duration_seconds: Any
    tool_errors_total: Any
    rag_requests_total: Any
    rag_retrieval_duration_seconds: Any
    policy_decisions_total: Any
    confirmation_results_total: Any
    escalations_total: Any
    agent_errors_total: Any
    memory_reads_total: Any
    memory_writes_total: Any
    memory_rejections_total: Any
    memory_forgets_total: Any
    dependency_failures_total: Any
    retry_attempts_total: Any
    retry_exhausted_total: Any
    degraded_requests_total: Any


def build_metrics(meter: Meter | None = None) -> ObservabilityMetrics:
    active_meter = meter or metrics.get_meter("agentic-customer-service-platform")
    return ObservabilityMetrics(
        agent_runs_total=active_meter.create_counter(
            "agent_runs_total", unit="{run}", description="Agent runs."
        ),
        agent_run_duration_seconds=active_meter.create_histogram(
            "agent_run_duration_seconds", unit="s", description="Agent run duration."
        ),
        tool_calls_total=active_meter.create_counter(
            "tool_calls_total", unit="{call}", description="Tool calls."
        ),
        tool_call_duration_seconds=active_meter.create_histogram(
            "tool_call_duration_seconds", unit="s", description="Tool call duration."
        ),
        tool_errors_total=active_meter.create_counter(
            "tool_errors_total", unit="{error}", description="Tool errors."
        ),
        rag_requests_total=active_meter.create_counter(
            "rag_requests_total", unit="{request}", description="RAG requests."
        ),
        rag_retrieval_duration_seconds=active_meter.create_histogram(
            "rag_retrieval_duration_seconds", unit="s", description="RAG retrieval duration."
        ),
        policy_decisions_total=active_meter.create_counter(
            "policy_decisions_total", unit="{decision}", description="Policy decisions."
        ),
        confirmation_results_total=active_meter.create_counter(
            "confirmation_results_total", unit="{result}", description="Confirmation results."
        ),
        escalations_total=active_meter.create_counter(
            "escalations_total", unit="{escalation}", description="Human escalations."
        ),
        agent_errors_total=active_meter.create_counter(
            "agent_errors_total", unit="{error}", description="Agent errors."
        ),
        memory_reads_total=active_meter.create_counter(
            "memory_reads_total", unit="{read}", description="Memory reads."
        ),
        memory_writes_total=active_meter.create_counter(
            "memory_writes_total", unit="{write}", description="Memory writes."
        ),
        memory_rejections_total=active_meter.create_counter(
            "memory_rejections_total", unit="{rejection}", description="Rejected memory candidates."
        ),
        memory_forgets_total=active_meter.create_counter(
            "memory_forgets_total", unit="{forget}", description="Memory forget operations."
        ),
        dependency_failures_total=active_meter.create_counter(
            "dependency_failures_total", unit="{failure}", description="Dependency failures."
        ),
        retry_attempts_total=active_meter.create_counter(
            "retry_attempts_total", unit="{attempt}", description="Retry attempts."
        ),
        retry_exhausted_total=active_meter.create_counter(
            "retry_exhausted_total", unit="{exhaustion}", description="Exhausted retries."
        ),
        degraded_requests_total=active_meter.create_counter(
            "degraded_requests_total", unit="{request}", description="Degraded requests."
        ),
    )


_metrics = build_metrics()


def get_metrics() -> ObservabilityMetrics:
    return _metrics


def configure_metrics(meter_provider: MeterProvider) -> ObservabilityMetrics:
    global _metrics
    _metrics = build_metrics(meter_provider.get_meter("agentic-customer-service-platform"))
    return _metrics
