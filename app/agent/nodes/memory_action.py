from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.schemas import AgentErrorCategory, Intent
from app.agent.state import AgentState
from app.memory.schemas import MemorySource
from app.memory.service import MemoryService
from app.observability.metrics import get_metrics
from app.observability.tracing import span


def make_memory_action_node(
    service: MemoryService, session: Session
) -> Callable[[AgentState], AgentState]:
    def memory_action(state: AgentState) -> AgentState:
        intent = state.get("intent")
        if intent == Intent.MEMORY_REMEMBER:
            candidate = state.get("memory_candidate")
            if candidate is None:
                return _failed(
                    AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
                    "A specific memory was not provided.",
                )
            with span("memory.evaluate_candidate") as memory_span:
                result = service.remember(
                    session,
                    state["customer_id"],
                    candidate,
                    source=MemorySource.USER_EXPLICIT,
                )
                memory_span.set_attribute("memory.type", candidate.memory_type.value)
                memory_span.set_attribute("memory.policy_outcome", result.status)
            if result.status in {"persisted", "deduplicated"}:
                with span(
                    "memory.persist",
                    attributes={
                        "memory.type": candidate.memory_type.value,
                        "memory.status": result.status,
                    },
                ):
                    pass
            if result.status in {"persisted", "deduplicated"}:
                get_metrics().memory_writes_total.add(1, {"status": result.status})
            else:
                get_metrics().memory_rejections_total.add(
                    1, {"reason": result.reason or result.status}
                )
            return {
                "memory_operation_status": result.status,
                "memory_policy_outcome": result.status,
                "last_error": None,
                "error_category": None
                if result.status in {"persisted", "deduplicated"}
                else AgentErrorCategory.POLICY_DENIED,
            }
        if intent == Intent.MEMORY_FORGET:
            key = state.get("memory_key")
            if not key:
                return _failed(
                    AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
                    "Please specify which memory to forget.",
                )
            with span("memory.forget", attributes={"memory.key": key}) as memory_span:
                result = service.forget(session, state["customer_id"], key)
                memory_span.set_attribute("memory.status", result.status)
            if result.status == "forgotten":
                get_metrics().memory_forgets_total.add(1, {"status": result.status})
            return {
                "memory_operation_status": result.status,
                "memory_policy_outcome": result.status,
                "last_error": None if result.status == "forgotten" else result.reason,
                "error_category": None
                if result.status in {"forgotten", "not_found"}
                else AgentErrorCategory.POLICY_DENIED,
            }
        return _failed(AgentErrorCategory.POLICY_DENIED, "Memory operation was not recognized.")

    return memory_action


def _failed(category: AgentErrorCategory, message: str) -> AgentState:
    return {
        "memory_operation_status": "rejected",
        "memory_policy_outcome": "reject",
        "last_error": message,
        "error_category": category,
    }
