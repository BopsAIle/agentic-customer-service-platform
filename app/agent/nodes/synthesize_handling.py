from app.agent.cskh import is_vietnamese_message
from app.agent.decision_compiler import ACTION_TOOLS
from app.agent.state import AgentState

_POSTURE_CONCLUSION_EN = {
    "likely_eligible_refund_or_return": (
        "Based on the order status and the reported issue, a refund or return is likely eligible "
        "and still needs confirmation before anything is submitted."
    ),
    "cancel_unavailable_offer_return": (
        "Cancellation is generally unavailable after shipment. A return or refund review may "
        "still be possible after delivery."
    ),
    "recommend_escalate": (
        "I don't have enough grounded policy evidence to resolve this safely, so a specialist "
        "should review it."
    ),
    "need_order_id": "I can continue once I have the order number.",
    "explain_policy": "Here is the relevant policy guidance for this request.",
    "offer_confirmed_write": (
        "I can submit the requested change after you confirm. Nothing has been executed yet."
    ),
    "write_blocked": (
        "I can explain the normal process, but I can't skip confirmation, policy checks, or "
        "execute a change from this request."
    ),
}
_POSTURE_CONCLUSION_VI = {
    "likely_eligible_refund_or_return": (
        "Với trạng thái đơn và tình huống bạn mô tả, đổi trả hoặc hoàn tiền có thể đủ điều kiện; "
        "hệ thống vẫn cần bạn xác nhận trước khi nộp yêu cầu."
    ),
    "cancel_unavailable_offer_return": (
        "Sau khi đơn đã giao vận, thường không hủy được. Bạn có thể theo dõi giao hàng hoặc hỏi "
        "về đổi trả/hoàn tiền sau khi nhận."
    ),
    "recommend_escalate": (
        "Hiện chưa đủ căn cứ chính sách đáng tin để kết luận, nên cần chuyên viên hỗ trợ xem giúp."
    ),
    "need_order_id": "Bạn cho mình mã đơn để tiếp tục kiểm tra nhé.",
    "explain_policy": "Dưới đây là hướng dẫn chính sách phù hợp với tình huống này.",
    "offer_confirmed_write": (
        "Mình có thể nộp yêu cầu sau khi bạn xác nhận. Chưa có thay đổi nào được thực hiện."
    ),
    "write_blocked": (
        "Mình giải thích được quy trình, nhưng không bỏ xác nhận hay tự ý thay đổi."
    ),
}
_NEXT_STEPS_EN = {
    "explain_only": (
        "If you want a refund, cancellation, or ticket, say so explicitly with the order number."
    ),
    "collect_order_id": "Could you provide your order number?",
    "offer_refund": "Would you like me to submit the refund request?",
    "offer_cancel": "Would you like me to submit the cancellation request?",
    "offer_ticket": "Would you like me to create a support ticket?",
    "escalate": "I can connect you with a support specialist if you want a human review.",
}
_NEXT_STEPS_VI = {
    "explain_only": "Nếu bạn muốn nộp hoàn tiền, hủy đơn hoặc tạo phiếu, hãy nói rõ và kèm mã đơn.",
    "collect_order_id": "Bạn cho mình mã đơn được không?",
    "offer_refund": "Bạn có muốn mình nộp yêu cầu hoàn tiền không?",
    "offer_cancel": "Bạn có muốn mình nộp yêu cầu hủy đơn không?",
    "offer_ticket": "Bạn có muốn mình tạo phiếu hỗ trợ không?",
    "escalate": "Mình có thể chuyển bạn cho chuyên viên nếu bạn muốn người thật xem giúp.",
}


def synthesize_handling(state: AgentState) -> AgentState:
    """Compose conclusion, grounded policy, and next steps without inventing limits."""

    recommendation = dict(state.get("handling_recommendation") or {})
    posture = str(recommendation.get("posture") or "explain_policy")
    suggested = str(recommendation.get("suggested_action") or "explain_only")
    vietnamese = _user_is_vietnamese(state)
    conclusions = _POSTURE_CONCLUSION_VI if vietnamese else _POSTURE_CONCLUSION_EN
    next_steps = _NEXT_STEPS_VI if vietnamese else _NEXT_STEPS_EN
    policy = _grounded_policy(state)
    conclusion = conclusions.get(posture, conclusions["explain_policy"])
    next_step = next_steps.get(suggested, next_steps["explain_only"])
    parts = [conclusion]
    if policy:
        parts.append(policy)
    parts.append(next_step)
    text = " ".join(part.strip() for part in parts if part and part.strip())
    recommendation["summary"] = text
    recommendation["conclusion"] = conclusion
    recommendation["next_step"] = next_step

    offer_write = (
        suggested in {"offer_refund", "offer_cancel", "offer_ticket"}
        and not state.get("write_blocked")
        and isinstance(state.get("proposed_write"), dict)
        and _proposed_write_is_complete(state)
    )
    updates: AgentState = {
        "handling_recommendation": recommendation,
        "offer_pending_write": offer_write,
    }
    if offer_write:
        proposed = state["proposed_write"]
        tool = proposed.get("tool")
        arguments = proposed.get("arguments")
        if isinstance(tool, str) and isinstance(arguments, dict):
            updates["selected_tool"] = tool
            updates["tool_arguments"] = dict(arguments)
            updates["request_type"] = state.get("request_type")
    elif state.get("selected_tool") in ACTION_TOOLS.values():
        updates["selected_tool"] = None
    return updates


def _grounded_policy(state: AgentState) -> str:
    answer = state.get("knowledge_answer") or ""
    grounding = state.get("answer_grounding") or {}
    if not answer or grounding.get("accepted") is False:
        return ""
    prefix = "Based on the retrieved evidence: "
    if answer.startswith(prefix):
        answer = answer[len(prefix) :]
    for citation in state.get("citations", []):
        citation_id = citation.get("citation_id")
        if isinstance(citation_id, str) and citation_id:
            answer = answer.replace(f" [{citation_id}]", "")
    return " ".join(answer.split())


def _user_is_vietnamese(state: AgentState) -> bool:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return is_vietnamese_message(message["content"])
    return False


def _proposed_write_is_complete(state: AgentState) -> bool:
    proposed = state.get("proposed_write") or {}
    arguments = proposed.get("arguments")
    tool = proposed.get("tool")
    if not isinstance(arguments, dict) or not isinstance(tool, str):
        return False
    if tool == "request_refund":
        return bool(arguments.get("order_id") and arguments.get("reason"))
    if tool == "cancel_order":
        return bool(arguments.get("order_id"))
    if tool == "create_support_ticket":
        return bool(arguments.get("category") and arguments.get("description"))
    if tool == "escalate_to_human":
        return bool(
            arguments.get("reason") and arguments.get("priority") and arguments.get("summary")
        )
    return False
