from collections.abc import Callable

from app.agent.llm.base import StructuredDecisionProvider
from app.agent.schemas import AgentErrorCategory, AgentRequestType, Intent
from app.agent.state import AgentState
from app.observability.tracing import span


def make_understand_request_node(
    provider: StructuredDecisionProvider,
) -> Callable[[AgentState], AgentState]:
    def understand_request(state: AgentState) -> AgentState:
        with span(
            "llm.structured_decision",
            attributes={
                "llm.provider": type(provider).__name__,
                "llm.operation": "structured_decision",
            },
        ) as llm_span:
            try:
                decision = provider.decide(
                    messages=state.get("messages", []), customer_id=state["customer_id"]
                )
            except Exception:
                llm_span.set_attribute("llm.status", "error")
                return {
                    "intent": Intent.UNKNOWN,
                    "request_type": AgentRequestType.UNCLEAR,
                    "last_error": "The request could not be classified.",
                    "error_category": AgentErrorCategory.LLM_ERROR,
                }
            llm_span.set_attribute("llm.status", "ok")
        return {
            "intent": decision.intent,
            "request_type": decision.request_type,
            "selected_tool": decision.tool_name,
            "tool_arguments": dict(decision.arguments),
            "decision_reason": decision.reason,
            "requires_retrieval": decision.requires_retrieval,
            "knowledge_query": decision.knowledge_query,
            "last_error": None,
            "error_category": None,
        }

    return understand_request
