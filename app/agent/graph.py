from collections.abc import Callable
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.agent.decision_compiler import CompileStatus
from app.agent.llm.base import DecisionProposalProvider
from app.agent.nodes.check_pending import make_check_pending_node
from app.agent.nodes.compile_decision import make_compile_decision_node
from app.agent.nodes.confirmed import make_confirmed_execution_node
from app.agent.nodes.create_pending import make_create_pending_node
from app.agent.nodes.evaluate_policy import make_evaluate_policy_node
from app.agent.nodes.human import make_human_escalation_node
from app.agent.nodes.memory_action import make_memory_action_node
from app.agent.nodes.respond import respond
from app.agent.nodes.retrieve_knowledge import make_retrieve_node
from app.agent.nodes.retrieve_memory import make_retrieve_memory_node
from app.agent.nodes.revalidate import make_revalidate_node
from app.agent.nodes.select_tool import select_tool
from app.agent.nodes.understand_request import make_understand_request_node
from app.agent.nodes.validate_tool import validate_tool
from app.agent.schemas import AgentErrorCategory, AgentRequestType, Intent
from app.agent.state import AgentState
from app.memory.service import MemoryService
from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.policies.confirmation import Clock
from app.policies.engine import PolicyEngine
from app.policies.models import PolicyOutcome
from app.policies.repository import PolicyAuditRepository
from app.rag.generation.grounded import GroundedAnswerGenerator
from app.rag.interfaces import KnowledgeRetriever
from app.resilience.config import ResilienceConfig
from app.tools import registry
from app.ui.projection import record_node


def _after_context(state: AgentState) -> str:
    return "respond" if state.get("error_category") is not None else "retrieve_memory"


def _after_pending(state: AgentState) -> str:
    confirmation_status = state.get("confirmation_status") or "normal"
    return {
        "normal": "understand_request",
        "confirmed": "policy_revalidation",
        "no_pending": "respond",
        "rejected": "respond",
        "expired": "respond",
        "ambiguous": "respond",
        "ownership_error": "respond",
    }.get(confirmation_status, "respond")


def _after_selection(state: AgentState) -> str:
    if state.get("error_category") is not None:
        return "respond"
    compile_result = state.get("compile_result")
    if compile_result is not None and compile_result.status == CompileStatus.CLARIFICATION_REQUIRED:
        return "respond"
    if state.get("intent") in {Intent.MEMORY_REMEMBER, Intent.MEMORY_FORGET}:
        return "memory_action"
    if state.get("request_type") in {
        AgentRequestType.INFORMATIONAL,
        AgentRequestType.UNCLEAR,
        AgentRequestType.KNOWLEDGE_ONLY,
    }:
        if state.get("requires_retrieval"):
            return "retrieve_knowledge"
        return "respond"
    return "validate_tool"


def _after_validation(state: AgentState) -> str:
    return "respond" if state.get("error_category") is not None else "evaluate_policy"


def _after_policy(state: AgentState) -> str:
    if state.get("error_category") is not None:
        return "respond"
    decision = state.get("policy_decision")
    if decision is None or decision.outcome == PolicyOutcome.DENY:
        return "respond"
    if decision.outcome == PolicyOutcome.ALLOW:
        return "execute_tool"
    if decision.outcome == PolicyOutcome.REQUIRE_CONFIRMATION:
        return "create_pending_action"
    return "execute_human_escalation"


def _after_revalidation(state: AgentState) -> str:
    return "respond" if state.get("error_category") is not None else "execute_confirmed_action"


def _after_execution(state: AgentState) -> str:
    if state.get("error_category") is not None:
        return "respond"
    return "retrieve_knowledge" if state.get("requires_retrieval") else "respond"


def _load_context(state: AgentState) -> AgentState:
    context = state.get("execution_context")
    if context is None:
        return {
            "intent": Intent.UNKNOWN,
            "request_type": AgentRequestType.UNCLEAR,
            "error_category": AgentErrorCategory.POLICY_DENIED,
            "last_error": "Authenticated execution context is required.",
            "selected_tool": None,
            "tool_result": None,
        }
    if state.get("conversation_id") != context.conversation_id:
        return {
            "intent": Intent.UNKNOWN,
            "request_type": AgentRequestType.UNCLEAR,
            "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
            "last_error": "Execution context does not match request state.",
            "selected_tool": None,
            "tool_result": None,
        }
    existing_customer = state.get("conversation_customer_id")
    existing_actor_id = state.get("conversation_actor_id")
    existing_actor_type = state.get("conversation_actor_type")
    principal = context.principal
    if (
        (existing_customer is not None and existing_customer != context.effective_customer_id)
        or (existing_actor_id is not None and existing_actor_id != principal.actor_id)
        or (existing_actor_type is not None and existing_actor_type != principal.actor_type.value)
    ):
        return {
            "intent": Intent.UNKNOWN,
            "request_type": AgentRequestType.UNCLEAR,
            "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
            "last_error": "Conversation belongs to a different execution context.",
            "selected_tool": None,
            "pending_action": state.get("pending_action"),
            "tool_result": None,
        }
    return {
        "conversation_customer_id": context.effective_customer_id,
        "conversation_actor_id": principal.actor_id,
        "conversation_actor_type": principal.actor_type.value,
        "agent_run_id": state["agent_run_id"],
        "retry_count": 0,
        "last_error": None,
        "error_category": None,
        "selected_tool": None,
        "tool_arguments": {},
        "semantic_decision": None,
        "compile_result": None,
        "tool_result": None,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "knowledge_answer": None,
        "citations": [],
        "requires_retrieval": False,
        "knowledge_query": None,
        "policy_decision": None,
        "confirmation_status": None,
        "tool_execution_status": None,
        "memory_context": [],
        "memory_candidate": None,
        "memory_key": None,
        "memory_operation_status": None,
        "memory_policy_outcome": None,
        "failure_category": None,
        "degraded_components": [],
        "recovery_action": None,
        "write_outcome_unknown": False,
    }


def _inspect_risk(state: AgentState) -> AgentState:
    return {}


def _instrument_node(
    name: str, node: Callable[[AgentState], AgentState]
) -> Callable[[AgentState], AgentState]:
    def instrumented(state: AgentState) -> AgentState:
        import time

        started = time.perf_counter()
        with span(
            f"agent.{name}", attributes={"agent.node": name, "node.name": name}
        ) as active_span:
            try:
                if name in {"execute_tool", "escalate"}:
                    result = _instrument_tool_node(name, node, state)
                else:
                    result = node(state)
                error = result.get("error_category")
                active_span.set_attribute("node.status", "error" if error else "ok")
                if error is not None:
                    active_span.set_attribute("error.category", error.value)
                selected_tool = result.get("selected_tool")
                if isinstance(selected_tool, str):
                    active_span.set_attribute("tool.selected", selected_tool)
                recovery = result.get("recovery_action")
                if isinstance(recovery, str):
                    active_span.set_attribute("recovery.action", recovery)
                    if recovery in {"degraded", "continue_without_memory"}:
                        get_metrics().degraded_requests_total.add(1, {"component": name})
                record_node(name, "error" if error else "ok", started)
                return result
            except Exception:
                record_node(name, "error", started)
                raise

    return instrumented


def _instrument_tool_node(
    node_name: str, node: Callable[[AgentState], AgentState], state: AgentState
) -> AgentState:
    import time

    tool_name = state.get("selected_tool") or "unknown"
    metadata = registry.TOOL_REGISTRY.get(tool_name)
    attributes: dict[str, str | int] = {"tool.name": tool_name}
    if metadata is not None:
        attributes.update(
            {
                "tool.operation_type": metadata.operation_type.value,
                "tool.risk_level": metadata.risk_level.value,
            }
        )
    started = time.perf_counter()
    status = "failed"
    with span("tool.execute", attributes=attributes) as tool_span:
        result = node(state)
        result_status = result.get("tool_execution_status")
        status = result_status if isinstance(result_status, str) else "not_executed"
        tool_span.set_attribute("tool.status", status)
        error_category = result.get("error_category")
        if error_category is not None:
            tool_span.set_attribute("error.category", error_category.value)
        metric_labels = {"tool_name": tool_name, "status": status}
        get_metrics().tool_calls_total.add(1, metric_labels)
        if status == "failed":
            get_metrics().tool_errors_total.add(
                1,
                {
                    "tool_name": tool_name,
                    "error_category": str(
                        getattr(error_category, "value", error_category or "unknown")
                    ),
                },
            )
        get_metrics().tool_call_duration_seconds.record(
            time.perf_counter() - started, {"tool_name": tool_name, "status": status}
        )
        if node_name == "escalate" and status == "executed":
            priority = state.get("tool_arguments", {}).get("priority", "unknown")
            tool_span.set_attribute("escalation.priority", str(priority))
            tool_span.set_attribute("escalation.reason_code", "customer_service_request")
            get_metrics().escalations_total.add(1, {"priority": str(priority)})
            tool_span.add_event("escalation.created")
        return result


def build_graph(
    provider: DecisionProposalProvider,
    session: Session,
    checkpointer: BaseCheckpointSaver[str],
    *,
    policy_engine: PolicyEngine,
    clock: Clock,
    ttl_seconds: int,
    audit_repository: PolicyAuditRepository,
    knowledge_retriever: KnowledgeRetriever,
    grounded_generator: GroundedAnswerGenerator,
    memory_service: MemoryService,
    resilience_config: ResilienceConfig,
    decision_contract_version: str = "direct_tool_v1",
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    graph.add_node("load_context", cast(Any, _instrument_node("load_context", _load_context)))
    graph.add_node(
        "check_pending_action",
        cast(
            Any,
            _instrument_node(
                "check_pending_action",
                make_check_pending_node(clock, ttl_seconds, audit_repository),
            ),
        ),
    )
    graph.add_node(
        "retrieve_memory",
        cast(
            Any,
            _instrument_node(
                "retrieve_memory",
                make_retrieve_memory_node(memory_service, session, resilience_config),
            ),
        ),
    )
    graph.add_node(
        "understand_request",
        cast(
            Any,
            _instrument_node(
                "understand_request",
                make_understand_request_node(
                    provider, resilience_config, decision_contract_version
                ),
            ),
        ),
    )
    graph.add_node(
        "select_tool_or_response", cast(Any, _instrument_node("route_request", select_tool))
    )
    graph.add_node(
        "compile_decision",
        cast(
            Any,
            _instrument_node(
                "compile_decision",
                make_compile_decision_node(session, decision_contract_version),
            ),
        ),
    )
    graph.add_node(
        "memory_action",
        cast(
            Any,
            _instrument_node("memory_action", make_memory_action_node(memory_service, session)),
        ),
    )
    graph.add_node("validate_tool", cast(Any, _instrument_node("validate_tool", validate_tool)))
    graph.add_node(
        "evaluate_policy",
        cast(
            Any,
            _instrument_node(
                "evaluate_policy", make_evaluate_policy_node(policy_engine, audit_repository, clock)
            ),
        ),
    )
    graph.add_node("inspect_risk", cast(Any, _instrument_node("inspect_risk", _inspect_risk)))
    graph.add_node(
        "create_pending_action",
        cast(
            Any,
            _instrument_node("create_pending_action", make_create_pending_node(clock)),
        ),
    )
    graph.add_node(
        "policy_revalidation",
        cast(
            Any,
            _instrument_node(
                "policy_revalidate", make_revalidate_node(session, audit_repository, clock)
            ),
        ),
    )
    graph.add_node(
        "execute_tool",
        cast(
            Any,
            _instrument_node(
                "execute_tool",
                make_confirmed_execution_node(session, resilience_config, audit_repository, clock),
            ),
        ),
    )
    graph.add_node(
        "execute_confirmed_action",
        cast(
            Any,
            _instrument_node(
                "execute_tool",
                make_confirmed_execution_node(session, resilience_config, audit_repository, clock),
            ),
        ),
    )
    graph.add_node(
        "execute_human_escalation",
        cast(
            Any,
            _instrument_node(
                "escalate", make_human_escalation_node(session, audit_repository, clock)
            ),
        ),
    )
    graph.add_node(
        "retrieve_knowledge",
        cast(
            Any,
            _instrument_node(
                "retrieve_knowledge",
                make_retrieve_node(knowledge_retriever, grounded_generator, resilience_config),
            ),
        ),
    )
    graph.add_node("respond", cast(Any, _instrument_node("respond", respond)))
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context",
        _after_context,
        {"retrieve_memory": "retrieve_memory", "respond": "respond"},
    )
    graph.add_edge("retrieve_memory", "check_pending_action")
    graph.add_conditional_edges(
        "check_pending_action",
        _after_pending,
        {
            "understand_request": "understand_request",
            "policy_revalidation": "policy_revalidation",
            "respond": "respond",
        },
    )
    graph.add_edge("understand_request", "compile_decision")
    graph.add_edge("compile_decision", "select_tool_or_response")
    graph.add_conditional_edges(
        "select_tool_or_response",
        _after_selection,
        {
            "validate_tool": "validate_tool",
            "memory_action": "memory_action",
            "retrieve_knowledge": "retrieve_knowledge",
            "respond": "respond",
        },
    )
    graph.add_conditional_edges(
        "validate_tool",
        _after_validation,
        {"evaluate_policy": "evaluate_policy", "respond": "respond"},
    )
    graph.add_edge("evaluate_policy", "inspect_risk")
    graph.add_conditional_edges(
        "inspect_risk",
        _after_policy,
        {
            "execute_tool": "execute_tool",
            "create_pending_action": "create_pending_action",
            "execute_human_escalation": "execute_human_escalation",
            "respond": "respond",
        },
    )
    graph.add_conditional_edges(
        "policy_revalidation",
        _after_revalidation,
        {"execute_confirmed_action": "execute_confirmed_action", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "execute_tool",
        _after_execution,
        {"retrieve_knowledge": "retrieve_knowledge", "respond": "respond"},
    )
    graph.add_edge("create_pending_action", "respond")
    graph.add_edge("memory_action", "respond")
    graph.add_edge("execute_confirmed_action", "respond")
    graph.add_edge("execute_human_escalation", "respond")
    graph.add_edge("retrieve_knowledge", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer)
