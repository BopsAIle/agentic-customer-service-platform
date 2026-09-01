from app.agent.cskh import HandlingPosture, SuggestedAction
from app.agent.schemas import Intent
from app.agent.state import AgentState

_DELIVERED = frozenset({"delivered", "completed"})
_SHIPPED = frozenset({"shipped", "in_transit"})
_PROCESSING = frozenset({"processing", "pending", "confirmed", "paid"})


def assess_situation(state: AgentState) -> AgentState:
    """Propose handling from situation, order state, and accepted grounding."""

    situation = state.get("situation") or {}
    category = situation.get("category", "other")
    goal = situation.get("customer_goal", "ask_policy")
    tool_result = state.get("tool_result") or {}
    order_status = str(tool_result.get("status") or "").casefold()
    grounding = state.get("answer_grounding") or {}
    accepted = bool(grounding.get("accepted"))
    write_blocked = bool(state.get("write_blocked"))
    proposed_write = state.get("proposed_write")
    intent = state.get("intent")
    has_order = _has_order_reference(state, tool_result)

    posture: HandlingPosture = "explain_policy"
    suggested: SuggestedAction = "explain_only"

    if write_blocked:
        posture = "write_blocked"
        suggested = "explain_only"
    elif not accepted and not state.get("knowledge_answer"):
        posture = "recommend_escalate"
        suggested = "escalate"
    elif goal in {"resolve_complaint", "request_action"} and not has_order:
        posture = "need_order_id"
        suggested = "collect_order_id"
    elif order_status in _DELIVERED and category in {
        "damage",
        "return_exchange",
        "billing",
    }:
        posture = "likely_eligible_refund_or_return"
        if proposed_write or intent is Intent.REFUND_REQUEST:
            suggested = "offer_refund"
        else:
            suggested = "explain_only"
    elif order_status in _SHIPPED and (
        intent is Intent.ORDER_CANCEL or category == "cancel"
    ):
        posture = "cancel_unavailable_offer_return"
        suggested = "explain_only"
    elif order_status in _PROCESSING and (
        intent is Intent.ORDER_CANCEL or category == "cancel"
    ):
        posture = "offer_confirmed_write"
        suggested = "offer_cancel"
    elif proposed_write:
        tool_name = str((proposed_write or {}).get("tool") or "")
        posture = "offer_confirmed_write"
        if tool_name == "cancel_order":
            suggested = "offer_cancel"
        elif tool_name == "create_support_ticket":
            suggested = "offer_ticket"
        else:
            suggested = "offer_refund"

    if write_blocked:
        suggested = "explain_only"

    return {
        "handling_recommendation": {
            "posture": posture,
            "suggested_action": suggested,
            "order_status": order_status or None,
            "grounding_accepted": accepted,
        }
    }


def _has_order_reference(state: AgentState, tool_result: dict[str, object]) -> bool:
    if tool_result.get("id") or tool_result.get("order_id"):
        return True
    arguments = state.get("tool_arguments") or {}
    if arguments.get("order_id"):
        return True
    proposed = state.get("proposed_write") or {}
    proposed_args = proposed.get("arguments")
    if isinstance(proposed_args, dict) and proposed_args.get("order_id"):
        return True
    entities = state.get("collected_entities") or {}
    return bool(entities.get("order_id"))
