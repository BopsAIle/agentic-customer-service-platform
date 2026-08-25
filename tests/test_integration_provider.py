import pytest

from app.agent.llm.integration import (
    DeterministicIntegrationDecisionProvider,
    DeterministicSemanticDecisionV3Provider,
)
from app.agent.schemas import AgentRequestType, Intent, SemanticDecisionV3


def test_integration_provider_returns_canonical_risk_two_cancellation() -> None:
    decision = DeterministicIntegrationDecisionProvider().decide(
        messages=[{"role": "user", "content": "  Cancel   order 3  "}],
        customer_id=2,
    )

    assert decision.intent == Intent.ORDER_CANCEL
    assert decision.request_type == AgentRequestType.WRITE_ACTION
    assert decision.tool_name == "cancel_order"
    assert decision.arguments == {"customer_id": 2, "order_id": 3}


def test_integration_provider_leaves_unsupported_text_unclassified() -> None:
    decision = DeterministicIntegrationDecisionProvider().decide(
        messages=[{"role": "user", "content": "Cancel order 99"}],
        customer_id=2,
    )

    assert decision.intent == Intent.UNKNOWN
    assert decision.request_type == AgentRequestType.UNCLEAR
    assert decision.tool_name is None


@pytest.mark.parametrize(
    ("message", "intent", "request_type"),
    [
        ("I want a refund.", Intent.REFUND_REQUEST, AgentRequestType.WRITE_ACTION),
        (
            "What is your refund policy?",
            Intent.REFUND_POLICY,
            AgentRequestType.KNOWLEDGE_ONLY,
        ),
        (
            "Remember that I prefer email communication.",
            Intent.MEMORY_REMEMBER,
            AgentRequestType.MEMORY_ACTION,
        ),
        (
            "I want to cancel my order.",
            Intent.ORDER_CANCEL,
            AgentRequestType.WRITE_ACTION,
        ),
    ],
)
def test_semantic_v3_integration_provider_matches_typed_contract(
    message: str, intent: Intent, request_type: AgentRequestType
) -> None:
    decision = DeterministicSemanticDecisionV3Provider().decide(
        messages=[{"role": "user", "content": message}], customer_id=1
    )

    assert isinstance(decision, SemanticDecisionV3)
    assert decision.intent == intent
    assert decision.request_type == request_type
    # The deterministic fixture uses the same typed payload validation boundary
    # as the function_calling adapter.
    assert SemanticDecisionV3.model_validate(decision.model_dump()) == decision


def test_semantic_v3_integration_provider_marks_random_text_for_clarification() -> None:
    decision = DeterministicSemanticDecisionV3Provider().decide(
        messages=[{"role": "user", "content": "asdfgh"}], customer_id=1
    )

    assert decision.intent == Intent.UNKNOWN
    assert decision.request_type == AgentRequestType.UNCLEAR
    assert decision.clarification_required is True


def test_semantic_v3_refund_target_and_policy_query_are_transport_safe() -> None:
    provider = DeterministicSemanticDecisionV3Provider()
    refund = provider.decide(
        messages=[
            {
                "role": "user",
                "content": "I received a damaged product and want a refund for order 1.",
            }
        ],
        customer_id=1,
    )
    policy = provider.decide(
        messages=[{"role": "user", "content": "What is your refund policy?"}],
        customer_id=1,
    )

    assert refund.target is not None
    assert refund.target.type == "explicit_order"
    assert refund.target.order_id == 1
    assert refund.reason == "damaged product"
    assert policy.requires_retrieval is True
    assert policy.knowledge_query == "What is your refund policy?"
