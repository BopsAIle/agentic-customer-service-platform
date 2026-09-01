"""Deterministic CSKH triage helpers. LLM proposals remain untrusted."""

from __future__ import annotations

import re
from typing import Final, Literal

from app.agent.schemas import Intent

CustomerGoal = Literal["ask_policy", "resolve_complaint", "request_action", "escalate"]
SituationCategory = Literal[
    "damage",
    "delay",
    "return_exchange",
    "warranty",
    "billing",
    "cancel",
    "other",
]
SuggestedAction = Literal[
    "explain_only",
    "collect_order_id",
    "offer_refund",
    "offer_cancel",
    "offer_ticket",
    "escalate",
]
HandlingPosture = Literal[
    "likely_eligible_refund_or_return",
    "cancel_unavailable_offer_return",
    "recommend_escalate",
    "need_order_id",
    "explain_policy",
    "offer_confirmed_write",
    "write_blocked",
]

_VIETNAMESE_CHARS = re.compile(
    r"[ăâêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵđ]",
    re.IGNORECASE,
)
_VIETNAMESE_MARKERS = re.compile(
    r"\b(?:đơn|mã đơn|hoàn tiền|hủy|đổi trả|bảo hành|hỏng|trễ|giao|không|"
    r"được không|sản phẩm|hàng)\b",
    re.IGNORECASE,
)
_DAMAGE = re.compile(
    r"\b(?:damaged|broken|cracked|dented|defective|móp|hỏng|vỡ|nứt|bể|hasarlı)\b",
    re.IGNORECASE,
)
_DELAY = re.compile(
    r"\b(?:delay|delayed|late|hasn't arrived|not arrived|trễ|chậm|chưa tới|"
    r"chưa nhận|kargo|teslimat)\b",
    re.IGNORECASE,
)
_RETURN_EXCHANGE = re.compile(
    r"\b(?:return|exchange|đổi trả|đổi hàng|trả hàng|iade|değişim)\b",
    re.IGNORECASE,
)
_WARRANTY = re.compile(
    r"\b(?:warranty|guarantee|bảo hành|garanti)\b",
    re.IGNORECASE,
)
_BILLING = re.compile(
    r"\b(?:refund|charge|billing|invoice|hoàn tiền|thanh toán|iade|para)\b",
    re.IGNORECASE,
)
_CANCEL = re.compile(
    r"\b(?:cancel|cancellation|hủy|hủy đơn|iptal)\b",
    re.IGNORECASE,
)
_POLICY_QUESTION = re.compile(
    r"\b(?:policy|how|what|when|eligible|can i|được không|như thế nào|"
    r"bao lâu|có được|có thể)\b",
    re.IGNORECASE,
)
_EXPLICIT_ACTION = re.compile(
    r"\b(?:please (?:refund|cancel|submit)|submit|request a refund|"
    r"i want a refund|hoàn tiền (?:đơn|giúp)|hủy đơn|"
    r"open a (?:support )?ticket|create a ticket)\b",
    re.IGNORECASE,
)
_URGENCY_HIGH = re.compile(
    r"\b(?:urgent|immediately|asap|gấp|khẩn|ngay lập tức|acilen)\b",
    re.IGNORECASE,
)
_CSKH_SUBSTANCE = re.compile(
    r"\b(?:order|refund|cancel|ticket|shipping|warranty|return|exchange|"
    r"policy|damaged|delay|delivery|đơn|hoàn|hủy|đổi|trả|bảo hành|"
    r"sipariş|iade|iptal|kargo)\b",
    re.IGNORECASE,
)

DEFAULT_KNOWLEDGE_QUERIES: Final[dict[Intent, str]] = {
    Intent.CAPABILITY_QUESTION: "customer support capabilities tickets orders refunds",
    Intent.REFUND_POLICY: "refund eligibility delivered damaged 30 calendar days",
    Intent.CANCELLATION_POLICY: "cancellation before shipment after shipment",
    Intent.SHIPPING_POLICY: "shipping processing transit delays",
    Intent.SUPPORT_FAQ: "support ticket contact order questions",
    Intent.REFUND_ELIGIBILITY: "refund eligibility policy",
    Intent.CANCELLATION_EXPLANATION: "cancellation after shipment",
    Intent.WARRANTY_POLICY: "warranty coverage period repair replacement",
    Intent.RETURN_EXCHANGE: "return exchange damaged wrong item timeframe",
}

SITUATION_KNOWLEDGE_QUERIES: Final[dict[str, str]] = {
    "damage": "refund eligibility delivered damaged returned 30 calendar days",
    "delay": "shipping delays tracking expected date",
    "return_exchange": "return exchange damaged wrong item",
    "warranty": "warranty coverage period repair replacement",
    "billing": "refund processing review settlement 3-5 business days",
    "cancel": "cancellation before shipment after shipment",
}


def is_vietnamese_message(message: str) -> bool:
    return bool(_VIETNAMESE_CHARS.search(message) or _VIETNAMESE_MARKERS.search(message))


def has_cskh_substance(message: str) -> bool:
    return bool(_CSKH_SUBSTANCE.search(message))


def infer_situation(
    message: str,
    *,
    intent: Intent | None = None,
) -> dict[str, str]:
    category = _situation_category(message, intent)
    goal = _customer_goal(message, intent, category)
    urgency = "high" if _URGENCY_HIGH.search(message) else "normal"
    if category in {"damage", "delay"} and goal == "resolve_complaint":
        urgency = "high" if urgency == "high" else "elevated"
    return {
        "category": category,
        "customer_goal": goal,
        "urgency": urgency,
        "language": "vi" if is_vietnamese_message(message) else "en",
    }


def knowledge_queries_for(
    *,
    intent: Intent | None,
    situation: dict[str, str] | None,
    order_status: str | None = None,
    compiler_query: str | None = None,
) -> list[str]:
    queries: list[str] = []
    if compiler_query and compiler_query.strip():
        queries.append(compiler_query.strip())
        category = (situation or {}).get("category")
        if category in {"damage", "delay", "return_exchange"} and intent in {
            Intent.REFUND_REQUEST,
            Intent.ORDER_CANCEL,
            Intent.REFUND_ELIGIBILITY,
        }:
            extra = SITUATION_KNOWLEDGE_QUERIES.get(category)
            if extra:
                queries.append(extra)
        return _dedupe_queries(queries)[:2]
    category = (situation or {}).get("category")
    if category and category in SITUATION_KNOWLEDGE_QUERIES:
        queries.append(SITUATION_KNOWLEDGE_QUERIES[category])
    if intent in DEFAULT_KNOWLEDGE_QUERIES:
        queries.append(DEFAULT_KNOWLEDGE_QUERIES[intent])
    status = (order_status or "").casefold()
    if status in {"delivered", "completed"}:
        queries.append("refund eligibility return exchange delivered 30 calendar days")
    elif status in {"shipped", "in_transit"}:
        queries.append("cancellation after shipment return refund")
    elif status in {"processing", "pending", "confirmed"}:
        queries.append("cancellation before shipment processing")
    return _dedupe_queries(queries)[:2] or ["refund eligibility shipping cancellation support"]


def _dedupe_queries(queries: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = " ".join(query.casefold().split())
        if key and key not in seen:
            seen.add(key)
            deduped.append(query)
    return deduped


def memory_query_for(message: str, situation: dict[str, str] | None) -> str:
    if not situation:
        return message
    parts = [
        situation.get("category") or "",
        situation.get("customer_goal") or "",
        "preference",
        "support context",
    ]
    return " ".join(part for part in parts if part)


def _situation_category(message: str, intent: Intent | None) -> SituationCategory:
    if intent is Intent.WARRANTY_POLICY or _WARRANTY.search(message):
        return "warranty"
    if intent is Intent.RETURN_EXCHANGE or _RETURN_EXCHANGE.search(message):
        return "return_exchange"
    if intent is Intent.ORDER_CANCEL or (
        _CANCEL.search(message) and not _POLICY_QUESTION.search(message)
    ):
        return "cancel"
    if _DAMAGE.search(message):
        return "damage"
    if intent in {Intent.SHIPPING_POLICY} or _DELAY.search(message):
        return "delay"
    if intent in {Intent.REFUND_REQUEST, Intent.REFUND_POLICY, Intent.REFUND_ELIGIBILITY} or (
        _BILLING.search(message)
    ):
        return "billing"
    if intent is Intent.CANCELLATION_POLICY:
        return "cancel"
    return "other"


def _customer_goal(
    message: str, intent: Intent | None, category: SituationCategory
) -> CustomerGoal:
    if intent is Intent.HUMAN_ESCALATION:
        return "escalate"
    if intent in {Intent.ORDER_CANCEL, Intent.REFUND_REQUEST, Intent.TICKET_CREATE}:
        if _POLICY_QUESTION.search(message) and not _EXPLICIT_ACTION.search(message):
            return "ask_policy"
        return "request_action"
    if intent in {
        Intent.REFUND_POLICY,
        Intent.CANCELLATION_POLICY,
        Intent.SHIPPING_POLICY,
        Intent.WARRANTY_POLICY,
        Intent.RETURN_EXCHANGE,
        Intent.SUPPORT_FAQ,
        Intent.CAPABILITY_QUESTION,
        Intent.REFUND_ELIGIBILITY,
        Intent.CANCELLATION_EXPLANATION,
    }:
        return "ask_policy"
    if _EXPLICIT_ACTION.search(message):
        return "request_action"
    if _POLICY_QUESTION.search(message):
        return "ask_policy"
    if category in {"damage", "delay", "return_exchange", "warranty", "billing"}:
        return "resolve_complaint"
    return "ask_policy"
