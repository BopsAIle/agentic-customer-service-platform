from app.agent.schemas import (
    AgentErrorCategory,
    AgentRequestType,
)
from app.agent.state import AgentState
from app.policies.models import PendingActionStatus


def _error_message(category: AgentErrorCategory | None) -> str:
    if category is None:
        return "I couldn't complete that request."
    return {
        AgentErrorCategory.RESOURCE_NOT_FOUND: "I couldn't find that customer-service resource.",
        AgentErrorCategory.OWNERSHIP_VIOLATION: "I can't access that resource for this customer.",
        AgentErrorCategory.INVALID_STATE: (
            "That action is not allowed in the resource's current state."
        ),
        AgentErrorCategory.DUPLICATE_ACTION: "That action is already in progress.",
        AgentErrorCategory.INVALID_TOOL_ARGUMENTS: (
            "I need a little more specific information to do that safely."
        ),
        AgentErrorCategory.UNKNOWN_TOOL: "I can't perform that operation.",
        AgentErrorCategory.POLICY_DENIED: "I can't authorize that operation.",
        AgentErrorCategory.LLM_ERROR: (
            "I couldn't understand that request reliably. Please rephrase it."
        ),
        AgentErrorCategory.RETRIEVAL_ERROR: (
            "The knowledge service is temporarily unavailable. Please try again."
        ),
        AgentErrorCategory.RERANKER_ERROR: (
            "The knowledge service could not rank results reliably. Please try again."
        ),
        AgentErrorCategory.CONFIRMATION_EXPIRED: (
            "That confirmation expired. Please request the action again."
        ),
    }[category]


def _tool_message(tool_name: str, result: dict[str, object] | None) -> str:
    if tool_name == "get_customer_orders":
        items = result.get("items", []) if result else []
        count = len(items) if isinstance(items, list) else 0
        return f"I found {count} order(s) for this customer."
    if tool_name == "get_customer_tickets":
        items = result.get("items", []) if result else []
        count = len(items) if isinstance(items, list) else 0
        return f"I found {count} support ticket(s) for this customer."
    if tool_name == "get_customer":
        return "I found the customer record."
    if tool_name == "get_order":
        return "I found the order record."
    if tool_name == "get_ticket":
        return "I found the support ticket."
    if tool_name == "create_support_ticket":
        return "Your support ticket was created."
    return "The requested business operation completed."


def respond(state: AgentState) -> AgentState:
    error_category = state.get("error_category")
    pending_action = state.get("pending_action")
    tool_name = state.get("selected_tool")
    memory_status = state.get("memory_operation_status")
    if memory_status == "persisted":
        message = "I’ll remember that for future support conversations."
    elif memory_status == "deduplicated":
        message = "I already had that preference and kept it current."
    elif memory_status == "reject":
        message = "I can't store that kind of information."
    elif memory_status == "require_explicit":
        message = "Please explicitly ask me to remember that before I store it."
    elif memory_status == "forgotten":
        message = "I forgot that memory."
    elif memory_status == "not_found":
        message = "I couldn’t find an active memory matching that request."
    elif state.get("knowledge_answer") is not None and error_category is None:
        message = state.get("knowledge_answer") or ""
    elif error_category is not None:
        message = _error_message(error_category)
    elif state.get("confirmation_status") == "no_pending":
        if pending_action is not None and pending_action.status == PendingActionStatus.EXECUTED:
            message = "That action was already completed; I did not execute it again."
        else:
            message = "There is no pending action to confirm."
    elif pending_action is not None:
        if pending_action.status == PendingActionStatus.PENDING:
            message = f"I can perform {pending_action.tool_name}, but confirmation is required."
        elif pending_action.status == PendingActionStatus.REJECTED:
            message = "I did not execute that action."
        elif pending_action.status == PendingActionStatus.EXPIRED:
            message = "That confirmation expired. Please request the action again."
        elif pending_action.status == PendingActionStatus.EXECUTED:
            message = _tool_message(pending_action.tool_name, state.get("tool_result"))
        elif pending_action.status == PendingActionStatus.FAILED:
            message = _error_message(error_category)
        else:
            message = "That action is no longer available."
    elif state.get("confirmation_status") == "ambiguous":
        message = "Please reply with a clear yes or no to the pending action."
    elif state.get("request_type") == AgentRequestType.INFORMATIONAL:
        message = (
            "I can look up customers, orders, and support tickets, create tickets, "
            "and help route requests."
        )
    elif state.get("request_type") == AgentRequestType.UNCLEAR:
        message = (
            "Could you clarify whether you need an order, ticket, cancellation, refund, "
            "or human assistance?"
        )
    elif tool_name:
        message = _tool_message(tool_name, state.get("tool_result"))
    else:
        message = "Could you clarify what you need help with?"
    message = _apply_memory_context(state, message)
    return {
        "final_response": message,
        "messages": [{"role": "assistant", "content": message}],
    }


def _apply_memory_context(state: AgentState, message: str) -> str:
    if state.get("error_category") is not None:
        return message
    memories = state.get("memory_context", [])
    keys = {str(item.get("normalized_key")): str(item.get("content")) for item in memories}
    if keys.get("response_style") == "The customer prefers concise answers." and len(message) > 240:
        first_sentence = message.split(". ", 1)[0].strip()
        if first_sentence:
            message = first_sentence + "."
    latest = " ".join(
        item["content"] for item in state.get("messages", []) if item["role"] == "user"
    ).casefold()
    if keys.get("contact_channel") and ("contact" in latest or "reach" in latest):
        channel = "email" if "email" in keys["contact_channel"].casefold() else "SMS"
        message += f" I’ll use your preferred {channel} support channel."
    return message
