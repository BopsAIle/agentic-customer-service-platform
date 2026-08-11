from collections.abc import Callable

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.policies.confirmation import (
    Clock,
    belongs_to_context,
    is_expired,
    parse_confirmation,
    transition,
)
from app.policies.models import PendingActionStatus


def make_check_pending_node(clock: Clock, ttl_seconds: int) -> Callable[[AgentState], AgentState]:
    def check_pending(state: AgentState) -> AgentState:
        with span("confirmation.evaluate") as confirmation_span:
            result = _check_pending(state, clock, ttl_seconds)
            status = result.get("confirmation_status") or "none"
            confirmation_span.set_attribute("confirmation.result", status)
            action = result.get("pending_action") or state.get("pending_action")
            if action is not None:
                confirmation_span.set_attribute("action.status", action.status.value)
            confirmation_span.set_attribute("action.expired", status == "expired")
            get_metrics().confirmation_results_total.add(1, {"result": status})
            return result

    return check_pending


def _check_pending(state: AgentState, clock: Clock, ttl_seconds: int) -> AgentState:
    action = state.get("pending_action")
    current_message = _latest_user_message(state)
    parsed = parse_confirmation(current_message)
    if action is None:
        return {"confirmation_status": "no_pending" if parsed != "ambiguous" else "normal"}
    context = state.get("execution_context")
    if context is None or not belongs_to_context(action, context):
        return {
            "confirmation_status": "ownership_error",
            "last_error": "Pending action belongs to another execution context.",
            "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
        }
    if action.status == PendingActionStatus.PENDING:
        if is_expired(action, clock.now(), ttl_seconds):
            return {
                "pending_action": transition(action, PendingActionStatus.EXPIRED),
                "confirmation_status": "expired",
            }
        if parsed == "confirmed":
            return {
                "pending_action": transition(action, PendingActionStatus.CONFIRMED),
                "confirmation_status": "confirmed",
            }
        if parsed == "rejected":
            return {
                "pending_action": transition(action, PendingActionStatus.REJECTED),
                "confirmation_status": "rejected",
            }
        return {"confirmation_status": "ambiguous"}
    if parsed == "confirmed":
        return {"confirmation_status": "no_pending"}
    return {"confirmation_status": "normal", "pending_action": None}


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
