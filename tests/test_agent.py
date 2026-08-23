from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import (
    AgentExecutionMode,
    AgentRequestType,
    Intent,
    StructuredDecision,
)
from app.api.routes.agent import get_agent_runtime
from app.core.config import LLMProvider
from app.main import app
from app.models import Escalation, Order
from app.models.entities import OrderStatus
from app.policies.confirmation import Clock
from app.policies.models import PendingActionStatus
from app.policies.repository import InMemoryPolicyAuditLog


class FakeClock(Clock):
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def assert_order_status(session: Session, order_id: int, expected: OrderStatus) -> None:
    order = session.get(Order, order_id)
    assert order is not None
    assert OrderStatus(order.status) == expected


def decision(
    intent: Intent,
    request_type: AgentRequestType,
    tool_name: str | None = None,
    arguments: dict[str, object] | None = None,
) -> StructuredDecision:
    return StructuredDecision(
        intent=intent,
        request_type=request_type,
        tool_name=tool_name,
        arguments=arguments or {},
        reason="deterministic test decision",
    )


def test_informational_request_does_not_execute_a_tool(db_session: Session) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [decision(Intent.CAPABILITY_QUESTION, AgentRequestType.INFORMATIONAL)]
        )
    )
    result = runtime.run(
        conversation_id="info-1",
        customer_id=1,
        message="What can you help me with?",
        session=db_session,
    )
    assert result.intent == Intent.CAPABILITY_QUESTION
    assert result.tool_call is None
    assert "look up" in result.message


def test_read_tool_executes_through_the_real_graph(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LIST,
                AgentRequestType.READ_ACTION,
                "get_customer_orders",
                {"customer_id": 1},
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="orders-1",
        customer_id=1,
        message="Show my orders.",
        session=db_session,
    )
    assert result.tool_call is not None
    assert result.tool_call.name == "get_customer_orders"
    assert result.tool_call.status == "executed"
    assert result.error_category is None


@pytest.mark.parametrize(
    ("intent", "tool_name", "arguments"),
    [
        (Intent.CUSTOMER_LOOKUP, "get_customer", {"customer_id": 1}),
        (Intent.ORDER_LOOKUP, "get_order", {"customer_id": 1, "order_id": 2}),
        (Intent.TICKET_LIST, "get_customer_tickets", {"customer_id": 1}),
        (Intent.TICKET_LOOKUP, "get_ticket", {"customer_id": 1, "ticket_id": 1}),
    ],
)
def test_all_customer_scoped_read_tools_execute(
    db_session: Session, intent: Intent, tool_name: str, arguments: dict[str, object]
) -> None:
    provider = FakeDecisionProvider(
        [decision(intent, AgentRequestType.READ_ACTION, tool_name, arguments)]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id=f"read-{tool_name}",
        customer_id=1,
        message="Look that up.",
        session=db_session,
    )
    assert result.tool_call is not None
    assert result.tool_call.status == "executed"


def test_risk_one_create_ticket_executes(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.TICKET_CREATE,
                AgentRequestType.WRITE_ACTION,
                "create_support_ticket",
                {
                    "customer_id": 1,
                    "order_id": 3,
                    "category": "delivery",
                    "description": "Please check my delivery.",
                },
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="ticket-1",
        customer_id=1,
        message="Create a ticket for my delivery.",
        session=db_session,
    )
    assert result.tool_call is not None
    assert result.tool_call.status == "executed"


def test_risk_two_cancel_is_pending_and_does_not_mutate(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="cancel-1",
        customer_id=1,
        message="Cancel my pending order.",
        session=db_session,
    )
    order = db_session.get(Order, 3)
    assert result.tool_call is None
    assert result.pending_action is not None
    assert result.pending_action.status == "pending"
    assert result.pending_action.risk_level == 2
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.PENDING


def test_confirmation_executes_exact_pending_action_and_is_idempotent(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            )
        ]
    )
    audit_log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(provider=provider, audit_log=audit_log)
    pending = runtime.run(
        conversation_id="confirm-1",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    executed = runtime.run(
        conversation_id="confirm-1",
        customer_id=1,
        message="yes",
        session=db_session,
    )
    repeated = runtime.run(
        conversation_id="confirm-1",
        customer_id=1,
        message="yes",
        session=db_session,
    )
    assert pending.pending_action is not None
    assert pending.pending_action.status == PendingActionStatus.PENDING
    assert executed.pending_action is not None
    assert executed.pending_action.status == PendingActionStatus.EXECUTED
    assert executed.pending_action.action_id == pending.pending_action.action_id
    assert executed.pending_action.arguments == pending.pending_action.arguments
    assert executed.tool_call is not None
    assert executed.tool_call.name == "cancel_order"
    assert repeated.pending_action is not None
    assert repeated.pending_action.status == PendingActionStatus.EXECUTED
    assert repeated.tool_call is None
    assert len(provider.calls) == 1
    assert audit_log.events[0].action_id == pending.pending_action.action_id
    assert_order_status(db_session, 3, OrderStatus.CANCELLED)


def test_rejection_and_ambiguous_confirmation_do_not_execute(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            ),
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 4},
            ),
        ]
    )
    runtime = AgentRuntime(provider=provider)
    runtime.run(
        conversation_id="reject-1",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    rejected = runtime.run(
        conversation_id="reject-1",
        customer_id=1,
        message="no",
        session=db_session,
    )
    assert rejected.pending_action is not None
    assert rejected.pending_action.status == PendingActionStatus.REJECTED
    assert_order_status(db_session, 3, OrderStatus.PENDING)

    runtime.run(
        conversation_id="ambiguous-1",
        customer_id=1,
        message="Cancel order 4.",
        session=db_session,
    )
    ambiguous = runtime.run(
        conversation_id="ambiguous-1",
        customer_id=1,
        message="yes, and refund order 999 too",
        session=db_session,
    )
    assert ambiguous.pending_action is not None
    assert ambiguous.pending_action.status == PendingActionStatus.PENDING
    assert_order_status(db_session, 4, OrderStatus.PROCESSING)
    assert len(provider.calls) == 2


def test_confirmation_revalidates_current_business_state(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 4},
            )
        ]
    )
    runtime = AgentRuntime(provider=provider)
    runtime.run(
        conversation_id="revalidate-1",
        customer_id=1,
        message="Cancel order 4.",
        session=db_session,
    )
    order = db_session.get(Order, 4)
    assert order is not None
    order.status = OrderStatus.SHIPPED
    db_session.commit()
    result = runtime.run(
        conversation_id="revalidate-1",
        customer_id=1,
        message="confirm",
        session=db_session,
    )
    assert result.error_category == "invalid_state"
    assert result.pending_action is not None
    assert result.pending_action.status == PendingActionStatus.FAILED
    assert_order_status(db_session, 4, OrderStatus.SHIPPED)


def test_expired_confirmation_cannot_execute(db_session: Session) -> None:
    clock = FakeClock()
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            )
        ]
    )
    runtime = AgentRuntime(provider=provider, clock=clock, confirmation_ttl_seconds=300)
    runtime.run(
        conversation_id="expire-1",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    clock.advance(301)
    result = runtime.run(
        conversation_id="expire-1",
        customer_id=1,
        message="yes",
        session=db_session,
    )
    assert result.pending_action is not None
    assert result.pending_action.status == PendingActionStatus.EXPIRED
    assert_order_status(db_session, 3, OrderStatus.PENDING)


def test_pending_action_cannot_cross_customer_or_conversation(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            )
        ]
    )
    runtime = AgentRuntime(provider=provider)
    runtime.run(
        conversation_id="private-1",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    wrong_customer = runtime.run(
        conversation_id="private-1",
        customer_id=2,
        message="yes",
        session=db_session,
    )
    other_conversation = runtime.run(
        conversation_id="private-2",
        customer_id=2,
        message="yes",
        session=db_session,
    )
    assert wrong_customer.pending_action is None
    assert wrong_customer.tool_call is None
    assert other_conversation.pending_action is None
    assert other_conversation.tool_call is None
    assert_order_status(db_session, 3, OrderStatus.PENDING)


def test_confirmation_without_pending_action_does_not_call_provider(db_session: Session) -> None:
    provider = FakeDecisionProvider([])
    result = AgentRuntime(provider=provider).run(
        conversation_id="no-pending-1",
        customer_id=1,
        message="yes",
        session=db_session,
    )
    assert result.pending_action is None
    assert result.tool_call is None
    assert len(provider.calls) == 0


def test_risk_three_escalation_is_pending_and_not_persisted(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.HUMAN_ESCALATION,
                AgentRequestType.ESCALATION,
                "escalate_to_human",
                {
                    "customer_id": 1,
                    "ticket_id": 1,
                    "reason": "Customer asked for a person.",
                    "priority": "high",
                    "summary": "Needs operator review.",
                },
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="escalation-1",
        customer_id=1,
        message="I need to speak to a human.",
        session=db_session,
    )
    assert result.pending_action is None
    assert result.tool_call is not None
    assert result.tool_call.status == "executed"
    assert db_session.scalar(select(Escalation)) is not None


def test_unknown_tool_is_rejected_without_dynamic_execution(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LOOKUP,
                AgentRequestType.READ_ACTION,
                "delete_everything",
                {"customer_id": 1},
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="unknown-tool-1",
        customer_id=1,
        message="Do something unusual.",
        session=db_session,
    )
    assert result.error_category == "unknown_tool"
    assert result.tool_call is None


def test_agent_rejects_cross_customer_arguments_before_execution(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LOOKUP,
                AgentRequestType.READ_ACTION,
                "get_order",
                {"customer_id": 2, "order_id": 5},
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="cross-customer-agent-1",
        customer_id=1,
        message="Show that order.",
        session=db_session,
    )
    assert result.error_category == "ownership_violation"
    assert result.tool_call is None


def test_invalid_arguments_are_rejected_deterministically(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [decision(Intent.ORDER_LOOKUP, AgentRequestType.READ_ACTION, "get_order", {})]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="invalid-args-1",
        customer_id=1,
        message="What about the second one?",
        session=db_session,
    )
    assert result.error_category == "invalid_tool_arguments"
    assert result.tool_call is None
    assert "specific" in result.message


def test_business_error_is_safe_and_does_not_expose_traceback(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LOOKUP,
                AgentRequestType.READ_ACTION,
                "get_order",
                {"order_id": 999},
            )
        ]
    )
    result = AgentRuntime(provider=provider).run(
        conversation_id="missing-order-1",
        customer_id=1,
        message="Show order 999.",
        session=db_session,
    )
    assert result.error_category == "resource_not_found"
    assert "Traceback" not in result.message


def test_conversation_state_is_retained_and_isolated(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LIST,
                AgentRequestType.READ_ACTION,
                "get_customer_orders",
                {"customer_id": 1},
            ),
            decision(
                Intent.ORDER_LOOKUP,
                AgentRequestType.READ_ACTION,
                "get_order",
                {"order_id": 2},
            ),
            decision(Intent.UNKNOWN, AgentRequestType.UNCLEAR),
        ]
    )
    runtime = AgentRuntime(provider=provider)
    first = runtime.run(
        conversation_id="conversation-a",
        customer_id=1,
        message="Show my orders.",
        session=db_session,
    )
    second = runtime.run(
        conversation_id="conversation-a",
        customer_id=1,
        message="What about the second one?",
        session=db_session,
    )
    separate = runtime.run(
        conversation_id="conversation-b",
        customer_id=1,
        message="What about the second one?",
        session=db_session,
    )
    assert first.tool_call is not None
    assert second.tool_call is not None
    assert second.tool_call.name == "get_order"
    assert len(provider.calls[1]) > 1
    assert separate.error_category is None
    assert len(provider.calls[2]) == 1


def test_agent_api_happy_path_and_pending_action(client: TestClient, db_session: Session) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LIST,
                    AgentRequestType.READ_ACTION,
                    "get_customer_orders",
                    {"customer_id": 1},
                ),
                decision(
                    Intent.ORDER_CANCEL,
                    AgentRequestType.WRITE_ACTION,
                    "cancel_order",
                    {"customer_id": 1, "order_id": 3},
                ),
            ]
        )
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        response = client.post(
            "/agent/chat",
            json={"conversation_id": "api-agent-1", "customer_id": 1, "message": "Show my orders"},
        )
        pending = client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-agent-1",
                "customer_id": 1,
                "message": "Cancel the third one",
            },
        )
        confirmed = client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-agent-1",
                "customer_id": 1,
                "message": "confirm",
            },
        )
        repeated = client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-agent-1",
                "customer_id": 1,
                "message": "yes",
            },
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)
    assert response.status_code == 200
    assert response.json()["tool_call"]["status"] == "executed"
    assert pending.status_code == 200
    assert pending.json()["pending_action"]["status"] == "pending"
    assert confirmed.status_code == 200
    assert confirmed.json()["pending_action"]["status"] == "executed"
    assert confirmed.json()["tool_call"]["status"] == "executed"
    assert repeated.status_code == 200
    assert repeated.json()["pending_action"]["status"] == "executed"
    assert repeated.json()["tool_call"] is None


def test_agent_api_validates_request_schema(client: TestClient) -> None:
    response = client.post("/agent/chat", json={"conversation_id": "bad", "customer_id": 1})
    assert response.status_code == 422


def test_live_proposal_mode_falls_back_without_openai_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [decision(Intent.CAPABILITY_QUESTION, AgentRequestType.INFORMATIONAL)]
        )
    )
    runtime.settings = runtime.settings.model_copy(
        update={
            "llm_provider": LLMProvider.OPENAI_COMPATIBLE,
            "llm_api_key": None,
            "llm_base_url": "http://localhost:11434/v1",
        }
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        response = client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-live-fallback-1",
                "customer_id": 1,
                "message": "What can you help me with?",
                "execution_mode": "live_proposal",
            },
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "recorded_replay"
    assert payload["fallback_message"] == "Live model unavailable. Showing bounded evidence replay."
    assert payload["provider"] == "recorded_evidence"
    assert "api_key" not in response.text.casefold()


def test_live_proposal_mode_requires_explicit_openai_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = AgentRuntime(provider=FakeDecisionProvider([]))
    marker = object()
    runtime.settings = runtime.settings.model_copy(
        update={
            "llm_provider": LLMProvider.OPENAI_COMPATIBLE,
            "llm_api_key": "test-only-key",
            "llm_base_url": "https://api.openai.com/v1",
        }
    )
    monkeypatch.setattr("app.agent.runtime.OpenAICompatibleProvider", lambda settings: marker)
    provider, contract, mode, fallback = runtime._provider_for_execution(
        AgentExecutionMode.LIVE_PROPOSAL
    )
    assert provider is marker
    assert contract == "semantic_decision_v3"
    assert mode == AgentExecutionMode.LIVE_PROPOSAL
    assert fallback is None


def test_agent_api_rejection_and_human_path(client: TestClient) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_CANCEL,
                    AgentRequestType.WRITE_ACTION,
                    "cancel_order",
                    {"customer_id": 1, "order_id": 3},
                ),
                decision(
                    Intent.HUMAN_ESCALATION,
                    AgentRequestType.ESCALATION,
                    "escalate_to_human",
                    {
                        "customer_id": 1,
                        "ticket_id": 1,
                        "reason": "Customer needs an operator.",
                        "priority": "high",
                        "summary": "Please review this case.",
                    },
                ),
            ]
        )
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        client.post(
            "/agent/chat",
            json={"conversation_id": "api-reject-1", "customer_id": 1, "message": "cancel order 3"},
        )
        rejected = client.post(
            "/agent/chat",
            json={"conversation_id": "api-reject-1", "customer_id": 1, "message": "no"},
        )
        human = client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-human-1",
                "customer_id": 1,
                "message": "I need a human",
            },
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)
    assert rejected.status_code == 200
    assert rejected.json()["pending_action"]["status"] == "rejected"
    assert human.status_code == 200
    assert human.json()["tool_call"]["status"] == "executed"


def test_agent_api_expired_confirmation(client: TestClient) -> None:
    clock = FakeClock()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_CANCEL,
                    AgentRequestType.WRITE_ACTION,
                    "cancel_order",
                    {"customer_id": 1, "order_id": 3},
                )
            ]
        ),
        clock=clock,
        confirmation_ttl_seconds=300,
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        client.post(
            "/agent/chat",
            json={"conversation_id": "api-expire-1", "customer_id": 1, "message": "cancel order 3"},
        )
        clock.advance(301)
        expired = client.post(
            "/agent/chat",
            json={"conversation_id": "api-expire-1", "customer_id": 1, "message": "yes"},
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)
    assert expired.status_code == 200
    assert expired.json()["pending_action"]["status"] == "expired"
