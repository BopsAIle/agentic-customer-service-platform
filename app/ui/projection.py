from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

from app.agent.schemas import AgentResponse
from app.agent.state import AgentState
from app.core.config import get_settings
from app.core.context import ExecutionContext
from app.policies.models import PendingActionStatus, PolicyAuditEvent
from app.ui.repository import InMemoryAgentRunProjectionRepository
from app.ui.schemas import (
    AgentRunView,
    UIAnswerGrounding,
    UICompilerDecision,
    UIConfirmationLifecycle,
    UIDecisionEvidence,
    UIGroundingEvidence,
    UIMemoryUsage,
    UIPolicyEvent,
    UIRagDocument,
    UIRetrievalMetadata,
    UITargetValidation,
    UIToolEvent,
    UITraceEvent,
    UIWriteOutcome,
)
from app.ui.trace import trace_event_key_for_node, trace_stage_for_node


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


class UIProjectionStore(InMemoryAgentRunProjectionRepository):
    def __init__(self, max_runs: int = 200) -> None:
        super().__init__(max_projections=max_runs)

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
        persist: bool = True,
    ) -> AgentRunView:
        view = self.build_view(
            projection,
            response=response,
            state=state,
            policy_events=policy_events,
            duration_ms=duration_ms,
        )
        if persist:
            self.upsert(view)
        projection.view = view
        return view

    def build_view(
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
                action_id=event.action_id,
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
        memory_count = len(memory_items)
        memory_view = UIMemoryUsage(
            item_count=memory_count,
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
            retrieved=memory_count > 0,
            retrieved_count=memory_count,
            items_used=memory_count,
            context_usage="context_enrichment" if memory_count else "not_used",
            purpose="context_enrichment" if memory_count else "not_used",
            decision_influence="context_only" if memory_count else "not_used",
            authority_influence="none" if memory_count else "not_applicable",
        )
        retrieval_metadata = UIRetrievalMetadata.model_validate(
            state.get("retrieval_metadata") or {}
        )
        answer_grounding = UIAnswerGrounding.model_validate(state.get("answer_grounding") or {})
        trace = []
        for node in projection.nodes:
            stage = trace_stage_for_node(node.name)
            trace_metadata: dict[str, str | int | float | bool] = {}
            if stage.value == "memory_context":
                trace_metadata = {
                    "items_used": memory_count,
                    "role": "context_enrichment" if memory_count else "not_used",
                }
            if node.name == "retrieve_knowledge":
                grounding_payload = answer_grounding.model_dump(exclude_none=True)
                trace_metadata.update(
                    {
                        key: value
                        for key, value in grounding_payload.items()
                        if isinstance(value, (str, int, float, bool))
                    }
                )
            if node.name == "understand_request":
                provider_metadata = state.get("provider_metadata")
                if provider_metadata is not None:
                    metadata_payload = provider_metadata.model_dump(exclude_none=True)
                    trace_metadata.update(
                        {
                            key: value
                            for key, value in metadata_payload.items()
                            if isinstance(value, (str, int, float, bool))
                        }
                    )
            trace.append(
                UITraceEvent(
                    name=node.name,
                    event_key=trace_event_key_for_node(node.name),
                    stage=stage,
                    status=node.status,
                    duration_ms=node.duration_ms,
                    timestamp=node.timestamp,
                    metadata=trace_metadata,
                )
            )
        pending_action = state.get("pending_action")
        run_status = "error" if response.error_category else "completed"
        if (
            not response.error_category
            and pending_action is not None
            and pending_action.status == PendingActionStatus.PENDING
        ):
            run_status = "waiting_confirmation"
        decision_evidence = _decision_evidence(state, policy_events, response)
        view = AgentRunView(
            run_id=projection.run_id,
            request_id=projection.context.request_id,
            conversation_id=projection.context.conversation_id,
            tenant_id=projection.context.tenant_id,
            action_id=_action_id(state),
            customer_id=projection.context.effective_customer_id,
            actor_id=projection.context.principal.actor_id,
            actor_type=projection.context.principal.actor_type.value,
            roles=list(projection.context.principal.roles),
            intent=response.intent.value,
            request_type=response.request_type.value,
            status=run_status,
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
            answer_grounding=answer_grounding,
            trace=trace,
            decision_reason=_decision_reason(state, policy_events, response),
            evidence=decision_evidence,
            execution_mode=response.execution_mode.value,
            provider=response.provider,
            model=response.model,
            fallback_message=response.fallback_message,
            proposal=response.proposal,
            provider_metadata=response.provider_metadata,
        )
        return view

    def get_run(self, run_id: str) -> AgentRunView | None:
        return self.get_by_run_id(run_id)

    def conversation(self, conversation_id: str) -> list[AgentRunView]:
        return self.list_for_conversation(conversation_id)


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


def _decision_evidence(
    state: AgentState,
    policy_events: list[PolicyAuditEvent],
    response: AgentResponse,
) -> UIDecisionEvidence:
    compile_result = state.get("compile_result")
    compiler_status = getattr(getattr(compile_result, "status", None), "value", None)
    compiler_reason: str | None = None
    if compiler_status in {"clarification_required", "compile_rejected"}:
        compiler_reason = _bounded_text(
            getattr(compile_result, "rejection_reason", None)
            or getattr(compile_result, "reason", None)
        )
    policy_decision = state.get("policy_decision")
    pending_action = state.get("pending_action")
    confirmation_required = bool(
        policy_decision is not None
        and getattr(getattr(policy_decision, "outcome", None), "value", None)
        == "require_confirmation"
    )
    confirmation_status: str
    confirmation_action_id: str | None
    confirmation_risk: int | None
    if pending_action is not None:
        confirmation_status = pending_action.status.value
        confirmation_action_id = pending_action.action_id
        confirmation_risk = pending_action.risk_level
    else:
        confirmation_status = state.get("confirmation_status") or (
            "required" if confirmation_required else "not_required"
        )
        confirmation_action_id = state.get("action_id")
        confirmation_risk = getattr(policy_decision, "risk_level", None)
    selected_tool = state.get("selected_tool")
    write_status = _write_outcome_status(state, response, selected_tool)
    return UIDecisionEvidence(
        grounding=UIGroundingEvidence(
            status=state.get("grounding_status", "not_recorded"),
            reference_type=state.get("grounding_reference_type"),
            trusted_source=state.get("grounding_trusted_source"),
        ),
        compiler=UICompilerDecision(
            status=compiler_status or "not_applicable",
            selected_tool=(
                getattr(compile_result, "selected_tool", None)
                if compile_result is not None
                else None
            ),
            requires_retrieval=bool(
                getattr(compile_result, "requires_retrieval", False)
                if compile_result is not None
                else False
            ),
            reason=compiler_reason,
        ),
        target_validation=UITargetValidation(
            status=state.get("target_validation_status", "not_recorded")
        ),
        confirmation=UIConfirmationLifecycle(
            status=str(confirmation_status),
            required=confirmation_required,
            action_id=confirmation_action_id,
            risk_level=confirmation_risk,
        ),
        write_outcome=UIWriteOutcome(status=write_status),
    )


def _decision_reason(
    state: AgentState,
    policy_events: list[PolicyAuditEvent],
    response: AgentResponse,
) -> str | None:
    """Return a deterministic explanation, never the provider's free-form reason."""

    compile_result = state.get("compile_result")
    compiler_status = getattr(getattr(compile_result, "status", None), "value", None)
    if compiler_status in {"clarification_required", "compile_rejected"}:
        return _bounded_text(
            getattr(compile_result, "rejection_reason", None)
            or getattr(compile_result, "reason", None)
        )
    if policy_events:
        event = policy_events[-1]
        outcome = event.policy_outcome.value
        return _bounded_text(f"Policy outcome: {outcome}.")
    if response.error_category is not None:
        return _bounded_text(f"Request blocked: {response.error_category.value}.")
    return None


def _write_outcome_status(
    state: AgentState,
    response: AgentResponse,
    selected_tool: str | None,
) -> str:
    if response.write_outcome_unknown or state.get("write_outcome_unknown"):
        return "unknown"
    if selected_tool is None or not _is_write_tool(selected_tool):
        return "not_applicable"
    execution_status = state.get("tool_execution_status")
    if execution_status == "executed":
        return "executed"
    if execution_status == "failed":
        return "failed"
    pending_action = state.get("pending_action")
    if pending_action is not None and pending_action.status == PendingActionStatus.PENDING:
        return "pending_confirmation"
    if pending_action is not None and pending_action.status in {
        PendingActionStatus.REJECTED,
        PendingActionStatus.EXPIRED,
    }:
        return "blocked"
    return "not_attempted"


def _is_write_tool(tool_name: str) -> bool:
    from app.tools import registry

    metadata = registry.TOOL_REGISTRY.get(tool_name)
    return bool(metadata and metadata.operation_type.value == "write")


def _bounded_text(value: object, limit: int = 300) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit]


def _action_id(state: AgentState) -> str | None:
    action_id = state.get("action_id")
    if isinstance(action_id, str) and action_id:
        return action_id
    action = state.get("pending_action")
    return action.action_id if action is not None else None


_projection_store = UIProjectionStore(max_runs=get_settings().agent_run_projection_memory_limit)


def get_projection_store() -> UIProjectionStore:
    return _projection_store
