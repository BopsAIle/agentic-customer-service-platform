from collections.abc import Callable

from app.agent.nodes.pending_payload import (
    restore_pending_arguments,
    restore_pending_decision,
    restored_field_count,
)
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.policies.models import PendingActionStatus


def make_restore_pending_node() -> Callable[[AgentState], AgentState]:
    def restore_pending(state: AgentState) -> AgentState:
        action = state.get("pending_action")
        if action is None or action.status != PendingActionStatus.CONFIRMED:
            return {
                "pending_action_restored": False,
                "restored_fields_count": 0,
                "compilation_resumed": False,
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Confirmed pending action payload is unavailable.",
            }
        arguments = restore_pending_arguments(action)
        decision = restore_pending_decision(action, arguments)
        if decision is None:
            return {
                "pending_action_restored": False,
                "restored_fields_count": 0,
                "compilation_resumed": False,
                "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
                "last_error": "Pending action intent is unavailable for compilation.",
            }
        return {
            "semantic_decision": decision,
            "intent": decision.intent,
            "request_type": decision.request_type,
            "selected_tool": action.tool_name,
            "tool_arguments": arguments,
            "collected_entities": dict(action.collected_entities),
            "decision_reason": action.validation_context.get("decision_reason"),
            "grounding_status": action.validation_context.get("grounding_status", "not_recorded"),
            "grounding_reference_type": action.validation_context.get("grounding_reference_type"),
            "grounding_trusted_source": action.validation_context.get("grounding_trusted_source"),
            "target_validation_status": action.validation_context.get(
                "target_validation_status", "not_recorded"
            ),
            "pending_action_restored": True,
            "restored_fields_count": restored_field_count(action, arguments),
            "compilation_resumed": True,
            "error_category": None,
            "last_error": None,
        }

    return restore_pending
