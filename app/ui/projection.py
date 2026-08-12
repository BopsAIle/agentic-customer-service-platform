from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

from app.agent.schemas import AgentResponse
from app.agent.state import AgentState
from app.core.context import ExecutionContext
from app.policies.models import PolicyAuditEvent
from app.ui.schemas import (
    AgentRunView,
    UIMemoryUsage,
    UIPolicyEvent,
    UIRagDocument,
    UIRetrievalMetadata,
    UIToolEvent,
    UITraceEvent,
)


@dataclass
class _NodeEvent:
    name: str
    status: str
    duration_ms: float
    timestamp: datetime


@dataclass
class _RunProjection:
    run_id: str
    context: ExecutionContext
    started_at: datetime
    trace_id: str | None
    nodes: list[_NodeEvent] = field(default_factory=list)
    view: AgentRunView | None = None


_current_run: ContextVar[_RunProjection | None] = ContextVar("ui_current_run", default=None)


class UIProjectionStore:
    def __init__(self, max_runs: int = 200) -> None:
        self.max_runs = max_runs
        self._runs: dict[str, AgentRunView] = {}
        self._order: list[str] = []

    @contextmanager
    def capture(
        self,
        *,
        run_id: str,
        context: ExecutionContext,
        trace_id: str | None,
    ) -> Iterator[_RunProjection]:
        projection = _RunProjection(
            run_id=run_id,
            context=context,
            started_at=datetime.now(UTC),
            trace_id=trace_id,
        )
        token = _current_run.set(projection)
        try:
            yield projection
        finally:
            _current_run.reset(token)

    def record_node(self, name: str, status: str, duration_ms: float) -> None:
        current = _current_run.get()
        if current is not None:
            current.nodes.append(_NodeEvent(name, status, duration_ms, datetime.now(UTC)))

    def finish(
        self,
        projection: _RunProjection,
        *,
        response: AgentResponse,
        state: AgentState,
        policy_events: list[PolicyAuditEvent],
        duration_ms: float,
    ) -> AgentRunView:
        tools: list[UIToolEvent] = []
        selected_tool = state.get("selected_tool")
        execution_status = state.get("tool_execution_status")
        if isinstance(selected_tool, str):
            metadata = state.get("tool_result")
            result_fields = sorted(metadata.keys())[:12] if isinstance(metadata, dict) else []
            tools.append(
                UIToolEvent(
                    name=selected_tool,
                    risk_level=_risk_level(selected_tool),
                    status=str(execution_status or "pending"),
                    duration_ms=_node_duration(projection.nodes, "execute_tool"),
                    result_fields=result_fields,
                )
            )
        policy = [
            UIPolicyEvent(
                event_id=event.event_id,
                request_id=event.request_id,
                conversation_id=event.conversation_id,
                timestamp=event.timestamp,
                stage=event.stage,
                confirmation_status=event.confirmation_status,
                revalidation=event.revalidation,
                execution_status=event.execution_status,
                actor_id=event.actor_id,
                actor_type=event.actor_type.value,
                roles=list(event.roles),
                effective_customer_id=event.effective_customer_id,
                tool_name=event.tool_name,
                risk_level=event.risk_level,
                outcome=event.policy_outcome.value,
                reason_codes=event.reason_codes[:10],
            )
            for event in policy_events
            if event.agent_run_id == projection.run_id
        ]
        chunks = state.get("retrieved_chunks")
        rag_documents = []
        if isinstance(chunks, list):
            for chunk in chunks[:10]:
                if isinstance(chunk, dict):
                    raw_score = chunk.get("rerank_score") or chunk.get("score") or 0.0
                    score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
                    rag_documents.append(
                        UIRagDocument(
                            citation_id=str(
                                chunk.get("chunk_id") or chunk.get("citation_id") or "unknown"
                            ),
                            title=str(chunk.get("title", "Knowledge document")),
                            section=str(chunk.get("section", "unknown")),
                            source=str(chunk.get("source", "unknown")),
                            score=score,
                        )
                    )
        memory = state.get("memory_context")
        memory_items = memory if isinstance(memory, list) else []
        memory_view = UIMemoryUsage(
            item_count=len(memory_items),
            keys=sorted(
                str(item.get("normalized_key"))
                for item in memory_items
                if isinstance(item, dict) and item.get("normalized_key")
            )[:10],
            types=sorted(
                str(item.get("memory_type"))
                for item in memory_items
                if isinstance(item, dict) and item.get("memory_type")
            )[:10],
        )
        retrieval_metadata = UIRetrievalMetadata.model_validate(
            state.get("retrieval_metadata") or {}
        )
        trace = [
            UITraceEvent(
                name=node.name,
                status=node.status,
                duration_ms=node.duration_ms,
                timestamp=node.timestamp,
            )
            for node in projection.nodes
        ]
        view = AgentRunView(
            run_id=projection.run_id,
            request_id=projection.context.request_id,
            conversation_id=projection.context.conversation_id,
            customer_id=projection.context.effective_customer_id,
            actor_id=projection.context.principal.actor_id,
            actor_type=projection.context.principal.actor_type.value,
            roles=list(projection.context.principal.roles),
            intent=response.intent.value,
            request_type=response.request_type.value,
            status="error" if response.error_category else "completed",
            started_at=projection.started_at,
            duration_ms=duration_ms,
            trace_id=projection.trace_id,
            path=[node.name for node in projection.nodes],
            failure_category=response.failure_category,
            degraded_components=response.degraded_components,
            recovery_action=response.recovery_action,
            memory=memory_view,
            tools=tools,
            policy=policy,
            rag_documents=rag_documents,
            retrieval_metadata=retrieval_metadata,
            trace=trace,
        )
        self._runs[view.run_id] = view
        self._order.append(view.run_id)
        while len(self._order) > self.max_runs:
            self._runs.pop(self._order.pop(0), None)
        projection.view = view
        return view

    def get_run(self, run_id: str) -> AgentRunView | None:
        return self._runs.get(run_id)

    def conversation(self, conversation_id: str) -> list[AgentRunView]:
        return [
            self._runs[run_id]
            for run_id in self._order
            if self._runs[run_id].conversation_id == conversation_id
        ]


def record_node(name: str, status: str, started: float) -> None:
    current = _current_run.get()
    if current is not None:
        current.nodes.append(
            _NodeEvent(name, status, (perf_counter() - started) * 1000, datetime.now(UTC))
        )


def current_projection() -> _RunProjection | None:
    return _current_run.get()


def _node_duration(nodes: list[_NodeEvent], name: str) -> float:
    return sum(node.duration_ms for node in nodes if node.name == name)


def _risk_level(tool_name: str) -> int | None:
    from app.tools.registry import TOOL_REGISTRY

    metadata = TOOL_REGISTRY.get(tool_name)
    return int(metadata.risk_level) if metadata else None


_projection_store = UIProjectionStore()


def get_projection_store() -> UIProjectionStore:
    return _projection_store
