from typing import cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from opentelemetry import trace
from sqlalchemy.orm import Session

from app.agent.graph import build_graph
from app.agent.llm.base import StructuredDecisionProvider
from app.agent.llm.integration import DeterministicIntegrationDecisionProvider
from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import AgentRequestType, AgentResponse, AgentToolCall, Intent
from app.agent.state import AgentState
from app.auth.models import ActorType, Principal
from app.core.config import LLMProvider, Settings, get_settings
from app.core.context import ExecutionContext
from app.memory.service import MemoryService
from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.persistence.checkpoint import (
    CheckpointBackend,
    MemoryCheckpointProvider,
    checkpoint_thread_id,
    checkpoint_thread_id_hash,
)
from app.policies.confirmation import Clock, SystemClock
from app.policies.engine import PolicyEngine
from app.policies.repository import (
    PolicyAuditRepository,
    build_policy_audit_repository,
)
from app.rag.generation.grounded import GroundedAnswerGenerator
from app.rag.interfaces import (
    KnowledgeRetriever,
    ManagedKnowledgeRetriever,
    ReadyKnowledgeRetriever,
)
from app.rag.retrieval.service import build_default_knowledge_service
from app.resilience.config import ResilienceConfig
from app.ui.projection import get_projection_store


class AgentRuntime:
    def __init__(
        self,
        provider: StructuredDecisionProvider | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        checkpoint_backend: CheckpointBackend = CheckpointBackend.MEMORY,
        policy_engine: PolicyEngine | None = None,
        clock: Clock | None = None,
        audit_log: PolicyAuditRepository | None = None,
        confirmation_ttl_seconds: int | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
        grounded_generator: GroundedAnswerGenerator | None = None,
        memory_service: MemoryService | None = None,
        resilience_config: ResilienceConfig | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        self.provider = provider or _build_decision_provider(settings)
        self.checkpointer = checkpointer or MemoryCheckpointProvider().checkpointer
        self.checkpoint_backend = checkpoint_backend
        self.policy_engine = policy_engine or PolicyEngine()
        self.clock = clock or SystemClock()
        self.audit_repository_override = audit_log
        # Exposed only when an explicit bounded test/local adapter is injected.
        self.audit_log = audit_log
        self.confirmation_ttl_seconds = (
            confirmation_ttl_seconds or settings.confirmation_ttl_seconds
        )
        self.knowledge_retriever = knowledge_retriever or build_default_knowledge_service(settings)
        self.grounded_generator = grounded_generator or GroundedAnswerGenerator(
            settings.rag_final_context_count
        )
        self.memory_service = memory_service or MemoryService(
            enabled=settings.memory_enabled,
            max_context_items=settings.memory_max_context_items,
            default_ttl_days=settings.memory_default_ttl_days,
            support_context_ttl_days=settings.memory_support_context_ttl_days,
        )
        self.resilience_config = resilience_config or ResilienceConfig.from_settings(settings)

    def close(self) -> None:
        if isinstance(self.knowledge_retriever, ManagedKnowledgeRetriever):
            self.knowledge_retriever.close()

    def is_ready(self) -> bool:
        if isinstance(self.knowledge_retriever, ReadyKnowledgeRetriever):
            return self.knowledge_retriever.is_ready()
        return True

    def run(
        self,
        *,
        message: str,
        session: Session,
        context: ExecutionContext | None = None,
        conversation_id: str | None = None,
        customer_id: int | None = None,
    ) -> AgentResponse:
        execution_context = context or _legacy_execution_context(conversation_id, customer_id)
        conversation_id = execution_context.conversation_id
        customer_id = execution_context.effective_customer_id
        thread_id = checkpoint_thread_id(execution_context)
        thread_id_hash = checkpoint_thread_id_hash(execution_context)
        agent_run_id = str(uuid4())
        metric = get_metrics()
        labels = {"status": "ok"}
        metric.agent_runs_total.add(1)
        with span(
            "agent.run",
            attributes={
                "agent.run_id": agent_run_id,
                "request.id": execution_context.request_id,
                "conversation.id": conversation_id,
                "actor.id": execution_context.principal.actor_id,
                "actor.type": execution_context.principal.actor_type.value,
                "actor.roles": execution_context.principal.roles,
                "customer.id": customer_id,
                "checkpoint.backend": self.checkpoint_backend.value,
                "checkpoint.thread_id": thread_id_hash,
            },
        ) as root_span:
            import time

            started = time.perf_counter()
            try:
                current_span = trace.get_current_span().get_span_context()
                trace_id = f"{current_span.trace_id:032x}" if current_span.is_valid else None
                projection_store = get_projection_store()
                audit_repository = self.audit_repository_override or build_policy_audit_repository(
                    self.settings, session
                )
                graph = build_graph(
                    self.provider,
                    session,
                    self.checkpointer,
                    policy_engine=self.policy_engine,
                    clock=self.clock,
                    ttl_seconds=self.confirmation_ttl_seconds,
                    audit_repository=audit_repository,
                    knowledge_retriever=self.knowledge_retriever,
                    grounded_generator=self.grounded_generator,
                    memory_service=self.memory_service,
                    resilience_config=self.resilience_config,
                )
                with projection_store.capture(
                    run_id=agent_run_id,
                    context=execution_context,
                    trace_id=trace_id,
                ) as projection:
                    state = cast(
                        AgentState,
                        graph.invoke(
                            {
                                "execution_context": execution_context,
                                "conversation_id": conversation_id,
                                "agent_run_id": agent_run_id,
                                "messages": [{"role": "user", "content": message}],
                            },
                            config={
                                "configurable": {
                                    "thread_id": thread_id,
                                },
                                "metadata": {
                                    "checkpoint_backend": self.checkpoint_backend.value,
                                    "thread_id_hash": thread_id_hash,
                                    "actor_id": execution_context.principal.actor_id,
                                    "actor_type": execution_context.principal.actor_type.value,
                                    "effective_customer_id": customer_id,
                                },
                            },
                        ),
                    )
                    response = _response_from_state(state)
                    projection_store.finish(
                        projection,
                        response=response,
                        state=state,
                        policy_events=audit_repository.list_for_agent_run(agent_run_id),
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                root_span.set_attribute("agent.intent", response.intent.value)
                root_span.set_attribute("agent.request_type", response.request_type.value)
                if response.error_category is not None:
                    labels["status"] = "error"
                    root_span.set_attribute("agent.status", "error")
                    root_span.set_attribute("error.category", response.error_category.value)
                else:
                    root_span.set_attribute("agent.status", "ok")
                return response
            except Exception as error:
                labels["status"] = "error"
                root_span.set_attribute("agent.status", "error")
                root_span.add_event(
                    "agent.persistence_or_execution_error",
                    attributes={
                        "checkpoint.backend": self.checkpoint_backend.value,
                        "checkpoint.thread_id": thread_id_hash,
                        "error.type": type(error).__name__,
                    },
                )
                raise
            finally:
                metric.agent_run_duration_seconds.record(time.perf_counter() - started, labels)
                if labels["status"] == "error":
                    metric.agent_errors_total.add(1, labels)


def _legacy_execution_context(
    conversation_id: str | None, customer_id: int | None
) -> ExecutionContext:
    if conversation_id is None or customer_id is None:
        raise ValueError("Execution context is required.")
    return ExecutionContext(
        request_id=str(uuid4()),
        conversation_id=conversation_id,
        principal=Principal(
            actor_id="legacy-runtime",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=customer_id,
    )


def _build_decision_provider(settings: Settings) -> StructuredDecisionProvider:
    if settings.llm_provider == LLMProvider.DETERMINISTIC_INTEGRATION:
        return DeterministicIntegrationDecisionProvider()
    return OpenAICompatibleProvider(settings)


def _response_from_state(state: AgentState) -> AgentResponse:
    tool_call = None
    if state.get("selected_tool") and state.get("tool_execution_status") in {
        "executed",
        "failed",
    }:
        tool_call = AgentToolCall(
            name=state["selected_tool"],
            status=state["tool_execution_status"] or "failed",
            result=state.get("tool_result"),
        )
    return AgentResponse(
        conversation_id=state["conversation_id"],
        agent_run_id=state["agent_run_id"],
        message=state["final_response"],
        intent=state.get("intent", Intent.UNKNOWN),
        request_type=state.get("request_type", AgentRequestType.UNCLEAR),
        tool_call=tool_call,
        pending_action=state.get("pending_action"),
        decision_reason=state.get("decision_reason"),
        error_category=state.get("error_category"),
        citations=state.get("citations", []),
        failure_category=state.get("failure_category"),
        degraded_components=state.get("degraded_components", []),
        recovery_action=state.get("recovery_action"),
        write_outcome_unknown=state.get("write_outcome_unknown", False),
    )
