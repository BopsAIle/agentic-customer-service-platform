from collections.abc import Sequence

from app.agent.schemas import (
    AgentRequestType,
    Intent,
    SemanticDecision,
    SemanticTarget,
    StructuredDecision,
)
from app.agent.state import ConversationMessage


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
