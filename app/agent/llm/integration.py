import re
from collections.abc import Sequence

from app.agent.schemas import (
    AgentRequestType,
    ExplicitOrderTargetV3,
    Intent,
    SemanticDecision,
    SemanticDecisionV3,
    SemanticTarget,
    StructuredDecision,
)
from app.agent.state import ConversationMessage
from app.memory.extraction import extract_memory_request


class DeterministicIntegrationDecisionProvider:
    """Integration-only provider for the canonical authenticated lifecycle smoke."""

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> StructuredDecision:
        del memory_context
        latest_user_message = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        normalized = " ".join(latest_user_message.casefold().strip().split())
        if customer_id == 2 and normalized == "cancel order 3":
            return StructuredDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                tool_name="cancel_order",
                arguments={"customer_id": 2, "order_id": 3},
                reason="Canonical deterministic integration cancellation scenario.",
            )
        return StructuredDecision(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
            reason="Unsupported deterministic integration scenario.",
        )


class DeterministicSemanticDecisionProvider:
    """Deterministic semantic_decision_v2 provider for integration tests."""

    decision_contract_version = "semantic_decision_v2"

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> SemanticDecision:
        del customer_id, memory_context
        latest_user_message = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        normalized = " ".join(latest_user_message.casefold().strip().split())
        if normalized == "cancel order 3":
            return SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=3),
                reason="Canonical deterministic integration cancellation scenario.",
            )
        return SemanticDecision(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
            reason="Unsupported deterministic integration scenario.",
        )


class DeterministicSemanticDecisionV3Provider:
    """Deterministic implementation of the semantic provider contract.

    The integration provider selects a bounded fixture payload, then validates
    that payload through the same typed semantic_decision_v3 boundary used by
    the structured-output adapter.  It must not compile tools or inject graph
    state directly.
    """

    decision_contract_version = "semantic_decision_v3"

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> SemanticDecisionV3:
        del customer_id, memory_context
        latest_user_message = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        normalized = " ".join(latest_user_message.casefold().strip().split())
        payload = _semantic_v3_fixture_payload(normalized, latest_user_message)
        # This is the deterministic equivalent of the function_calling adapter
        # returning parsed arguments.  Keeping validation here ensures malformed
        # fixture payloads fail at the same contract boundary as live responses.
        return SemanticDecisionV3.model_validate(payload)


_ORDER_ID = re.compile(r"\border\s*(?:number|id)?\s*#?\s*(\d+)\b", re.IGNORECASE)


def _semantic_v3_fixture_payload(normalized: str, original: str) -> dict[str, object]:
    """Select only deterministic semantic proposals; compilation stays downstream."""

    memory_candidate, memory_key = extract_memory_request(original)
    if memory_candidate is not None:
        return {
            "intent": Intent.MEMORY_REMEMBER,
            "request_type": AgentRequestType.MEMORY_ACTION,
            "reason": "The customer explicitly requested a bounded memory update.",
            "memory_candidate": memory_candidate.model_dump(mode="json"),
            "memory_key": memory_key,
        }

    order_match = _ORDER_ID.search(original)
    order_id = int(order_match.group(1)) if order_match else None
    target = (
        ExplicitOrderTargetV3(type="explicit_order", order_id=order_id).model_dump(mode="json")
        if order_id is not None
        else None
    )

    if "refund" in normalized and any(
        marker in normalized for marker in ("policy", "how", "eligibility", "return process")
    ):
        return {
            "intent": Intent.REFUND_POLICY,
            "request_type": AgentRequestType.KNOWLEDGE_ONLY,
            "reason": "The customer asked for refund policy information.",
            "requires_retrieval": True,
            "knowledge_query": original.strip(),
        }

    if "refund" in normalized or "reimburse" in normalized or "money back" in normalized:
        reason = (
            "damaged product"
            if "damaged" in normalized and "product" in normalized
            else "damaged"
            if "damaged" in normalized
            else ""
        )
        return {
            "intent": Intent.REFUND_REQUEST,
            "request_type": AgentRequestType.WRITE_ACTION,
            "target": target,
            "reason": reason,
        }

    if "cancel" in normalized or "cancellation" in normalized:
        return {
            "intent": Intent.ORDER_CANCEL,
            "request_type": AgentRequestType.WRITE_ACTION,
            "target": target,
            "reason": "The customer requested order cancellation.",
        }

    if any(
        marker in normalized for marker in ("where is my order", "order status", "check my order")
    ):
        return {
            "intent": Intent.ORDER_LOOKUP,
            "request_type": AgentRequestType.READ_ACTION,
            "target": target,
            "reason": "The customer requested order status information.",
        }

    if any(
        marker in normalized for marker in ("human agent", "human specialist", "speak with a human")
    ):
        return {
            "intent": Intent.HUMAN_ESCALATION,
            "request_type": AgentRequestType.ESCALATION,
            "reason": "The customer requested human support.",
        }

    return {
        "intent": Intent.UNKNOWN,
        "request_type": AgentRequestType.UNCLEAR,
        "reason": "The request could not be classified by the deterministic provider.",
        "clarification_required": True,
    }
