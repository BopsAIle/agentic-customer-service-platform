from collections.abc import Callable

from opentelemetry.trace import Span
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.agent.nodes.common import error_category
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.agent.tool_catalog import get_agent_tool_definition
from app.observability.tracing import span
from app.policies.models import PendingAction, PendingActionStatus
from app.tools.base import ToolError
from app.tools.orders import CancelOrderInput, validate_cancel_order
from app.tools.refunds import RequestRefundInput, validate_refund_request


def make_revalidate_node(session: Session) -> Callable[[AgentState], AgentState]:
    def revalidate(state: AgentState) -> AgentState:
        action = state.get("pending_action")
        with span(
            "policy.revalidate",
            attributes={"action.status": action.status.value if action else "none"},
        ) as policy_span:
            if action is None or action.status != PendingActionStatus.CONFIRMED:
                policy_span.set_attribute("policy.outcome", "deny")
                return _failed(
                    state,
                    AgentErrorCategory.POLICY_DENIED,
                    "There is no confirmable pending action.",
                )
            return _revalidate_action(state, session, action, policy_span)

    return revalidate


def _revalidate_action(
    state: AgentState, session: Session, action: PendingAction, policy_span: Span
) -> AgentState:
    if action.conversation_id != state.get("conversation_id") or action.customer_id != state.get(
        "customer_id"
    ):
        policy_span.set_attribute("policy.outcome", "deny")
        return _failed(
            state, AgentErrorCategory.OWNERSHIP_VIOLATION, "Pending action ownership failed."
        )
    try:
        definition = get_agent_tool_definition(action.tool_name)
        if definition is None:
            policy_span.set_attribute("policy.outcome", "deny")
            return _failed(
                state, AgentErrorCategory.UNKNOWN_TOOL, "Pending tool is not registered."
            )
        arguments = definition.input_model.model_validate(action.arguments)
        if action.tool_name == "cancel_order":
            validate_cancel_order(session, CancelOrderInput.model_validate(arguments))
        elif action.tool_name == "request_refund":
            validate_refund_request(session, RequestRefundInput.model_validate(arguments))
        else:
            policy_span.set_attribute("policy.outcome", "deny")
            return _failed(
                state, AgentErrorCategory.POLICY_DENIED, "Pending tool is not revalidatable."
            )
        policy_span.set_attribute("policy.outcome", "allow")
        return {
            "selected_tool": action.tool_name,
            "tool_arguments": action.arguments,
            "error_category": None,
            "last_error": None,
        }
    except PydanticValidationError:
        policy_span.set_attribute("policy.outcome", "deny")
        return _failed(
            state, AgentErrorCategory.INVALID_TOOL_ARGUMENTS, "Pending arguments are invalid."
        )
    except ToolError as error:
        policy_span.set_attribute("policy.outcome", "deny")
        return _failed(state, error_category(error), str(error))


def _failed(state: AgentState, category: AgentErrorCategory, message: str) -> AgentState:
    action = state.get("pending_action")
    return {
        "pending_action": action.model_copy(update={"status": PendingActionStatus.FAILED})
        if action is not None
        else None,
        "error_category": category,
        "last_error": message,
    }
