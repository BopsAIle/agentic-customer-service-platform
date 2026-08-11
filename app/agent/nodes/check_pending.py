from collections.abc import Callable

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.policies.confirmation import Clock, is_expired, parse_confirmation, transition
from app.policies.models import PendingActionStatus


def make_check_pending_node(clock: Clock, ttl_seconds: int) -> Callable[[AgentState], AgentState]:
    def check_pending(state: AgentState) -> AgentState:
        action = state.get("pending_action")
        current_message = _latest_user_message(state)
        parsed = parse_confirmation(current_message)
        if action is None:
            return {"confirmation_status": "no_pending" if parsed != "ambiguous" else "normal"}
        if action.conversation_id != state.get("conversation_id"):
            return {
                "confirmation_status": "ownership_error",
                "last_error": "Pending action belongs to another conversation.",
                "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
            }
        if action.customer_id != state.get("customer_id"):
            return {
                "confirmation_status": "ownership_error",
                "last_error": "Pending action belongs to another customer.",
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

    return check_pending


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
