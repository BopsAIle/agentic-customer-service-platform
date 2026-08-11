from app.agent.llm.integration import DeterministicIntegrationDecisionProvider
from app.agent.schemas import AgentRequestType, Intent


def test_integration_provider_returns_canonical_risk_two_cancellation() -> None:
    decision = DeterministicIntegrationDecisionProvider().decide(
        messages=[{"role": "user", "content": "  Cancel   order 3  "}],
        customer_id=2,
    )

    assert decision.intent == Intent.ORDER_CANCEL
    assert decision.request_type == AgentRequestType.WRITE_ACTION
    assert decision.tool_name == "cancel_order"
    assert decision.arguments == {"customer_id": 2, "order_id": 3}


def test_integration_provider_does_not_generalize_outside_canonical_scenario() -> None:
    decision = DeterministicIntegrationDecisionProvider().decide(
        messages=[{"role": "user", "content": "Cancel order 99"}],
        customer_id=2,
    )

    assert decision.intent == Intent.UNKNOWN
    assert decision.request_type == AgentRequestType.UNCLEAR
    assert decision.tool_name is None
