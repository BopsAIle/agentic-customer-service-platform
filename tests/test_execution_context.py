from datetime import datetime
from typing import cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.nodes.retrieve_memory import make_retrieve_memory_node
from app.agent.runtime import AgentRuntime
from app.agent.schemas import (
    AgentExecutionMode,
    AgentRequestType,
    AgentResponse,
    Intent,
    StructuredDecision,
)
from app.agent.state import AgentState
from app.api.routes.agent import get_agent_runtime
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.main import app
from app.memory.schemas import MemoryRecordView
from app.memory.service import MemoryService
from app.models import Order
from app.models.entities import OrderStatus
from app.policies.repository import InMemoryPolicyAuditLog
from app.ui.projection import get_projection_store

TEST_CUSTOMER_ONE_TOKEN = "test-customer-one-token"


def execution_context(
    *,
    actor_id: str = "customer-one",
    actor_type: ActorType = ActorType.CUSTOMER,
    customer_id: int = 1,
    conversation_id: str = "context-test",
) -> ExecutionContext:
    principal_customer_id = customer_id if actor_type == ActorType.CUSTOMER else None
    roles = ["customer"] if actor_type == ActorType.CUSTOMER else ["support_operator"]
    return ExecutionContext(
        request_id=f"req-{actor_id}-{customer_id}",
        conversation_id=conversation_id,
        principal=Principal(
            actor_id=actor_id,
            actor_type=actor_type,
            roles=roles,
            customer_id=principal_customer_id,
            credential_id="safe-credential-reference",
        ),
        effective_customer_id=customer_id,
    )


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
        reason="execution context test",
    )


class CapturingRuntime(AgentRuntime):
    def __init__(self) -> None:
        super().__init__(
            provider=FakeDecisionProvider(
                [decision(Intent.CAPABILITY_QUESTION, AgentRequestType.INFORMATIONAL)]
            )
        )
        self.captured_context: ExecutionContext | None = None

    def run(
        self,
        *,
        message: str,
        session: Session,
        context: ExecutionContext | None = None,
        conversation_id: str | None = None,
        customer_id: int | None = None,
        execution_mode: AgentExecutionMode = AgentExecutionMode.RECORDED_REPLAY,
    ) -> AgentResponse:
        self.captured_context = context
        return super().run(
            message=message,
            session=session,
            context=context,
            conversation_id=conversation_id,
            customer_id=customer_id,
            execution_mode=execution_mode,
        )


class RecordingMemoryService(MemoryService):
    def __init__(self) -> None:
        super().__init__()
        self.retrieve_calls = 0

    def retrieve(
        self,
        session: Session,
        customer_id: int,
        query: str,
        now: datetime | None = None,
        principal: Principal | None = None,
    ) -> list[MemoryRecordView]:
        del session, customer_id, query, now, principal
        self.retrieve_calls += 1
        return []


def test_authenticated_principal_reaches_agent_with_server_derived_scope(
    client: TestClient,
) -> None:
    runtime = CapturingRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        response = client.post(
            "/agent/chat",
            json={
                "conversation_id": "http-context",
                "customer_id": 1,
                "message": "What can you do?",
            },
            headers={"Authorization": f"Bearer {TEST_CUSTOMER_ONE_TOKEN}"},
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)

    assert response.status_code == 200
    assert runtime.captured_context is not None
    assert runtime.captured_context.principal.actor_id == "customer-test-1"
    assert runtime.captured_context.effective_customer_id == 1
    assert runtime.captured_context.conversation_id == "http-context"
    assert runtime.captured_context.request_id


def test_forged_http_customer_scope_never_reaches_agent(client: TestClient) -> None:
    runtime = CapturingRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        response = client.post(
            "/agent/chat",
            json={
                "conversation_id": "forged-context",
                "customer_id": 2,
                "message": "Show my orders",
            },
            headers={"Authorization": f"Bearer {TEST_CUSTOMER_ONE_TOKEN}"},
        )
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)

    assert response.status_code == 404
    assert runtime.captured_context is None


def test_llm_customer_id_cannot_override_execution_context(db_session: Session) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LOOKUP,
                    AgentRequestType.READ_ACTION,
                    "get_order",
                    {"customer_id": 2, "order_id": 5},
                )
            ]
        ),
    )

    result = runtime.run(
        context=execution_context(),
        message="Show that order",
        session=db_session,
    )

    assert result.error_category == "ownership_violation"
    assert result.tool_call is None


def test_memory_cannot_be_read_without_execution_context(db_session: Session) -> None:
    service = RecordingMemoryService()
    node = make_retrieve_memory_node(service, db_session)

    result = node(
        cast(
            AgentState,
            {"messages": [{"role": "user", "content": "What do you remember?"}]},
        ),
    )

    assert result["error_category"] == "policy_denied"
    assert result["memory_context"] == []
    assert service.retrieve_calls == 0


def test_pending_confirmation_isolated_from_different_actor(db_session: Session) -> None:
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
    first_context = execution_context(conversation_id="actor-bound-confirmation")
    pending = runtime.run(
        context=first_context,
        message="Cancel order 3",
        session=db_session,
    )
    other_actor_context = execution_context(
        actor_id="operator-two",
        actor_type=ActorType.SUPPORT_OPERATOR,
        conversation_id="actor-bound-confirmation",
    )
    attempted = runtime.run(
        context=other_actor_context,
        message="evet",
        session=db_session,
    )

    assert pending.pending_action is not None
    assert pending.pending_action.actor_id == first_context.principal.actor_id
    assert pending.pending_action.actor_type == first_context.principal.actor_type
    assert pending.pending_action.effective_customer_id == 1
    assert attempted.pending_action is None
    assert attempted.tool_call is None
    order = db_session.get(Order, 3)
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.PENDING


def test_pending_confirmation_rejects_different_customer_scope(db_session: Session) -> None:
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
    operator_customer_one = execution_context(
        actor_id="operator-one",
        actor_type=ActorType.SUPPORT_OPERATOR,
        customer_id=1,
        conversation_id="customer-bound-confirmation",
    )
    runtime.run(
        context=operator_customer_one,
        message="Cancel order 3",
        session=db_session,
    )
    operator_customer_two = execution_context(
        actor_id="operator-one",
        actor_type=ActorType.SUPPORT_OPERATOR,
        customer_id=2,
        conversation_id="customer-bound-confirmation",
    )
    attempted = runtime.run(
        context=operator_customer_two,
        message="evet",
        session=db_session,
    )

    assert attempted.pending_action is None
    assert attempted.tool_call is None
    order = db_session.get(Order, 3)
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.PENDING


def test_same_conversation_id_is_isolated_between_principals(db_session: Session) -> None:
    provider = FakeDecisionProvider(
        [
            decision(
                Intent.ORDER_LIST,
                AgentRequestType.READ_ACTION,
                "get_customer_orders",
                {"customer_id": 1},
            ),
            decision(Intent.UNKNOWN, AgentRequestType.UNCLEAR),
        ]
    )
    runtime = AgentRuntime(provider=provider)
    runtime.run(
        context=execution_context(actor_id="actor-one", conversation_id="shared-id"),
        message="Show my orders",
        session=db_session,
    )
    runtime.run(
        context=execution_context(actor_id="actor-two", conversation_id="shared-id"),
        message="What about that list?",
        session=db_session,
    )

    assert len(provider.calls[0]) == 1
    assert len(provider.calls[1]) == 1


def test_policy_audit_and_run_projection_include_safe_identity_metadata(
    db_session: Session,
) -> None:
    context = execution_context(actor_id="audited-actor", conversation_id="audit-context")
    audit_log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                decision(
                    Intent.ORDER_LIST,
                    AgentRequestType.READ_ACTION,
                    "get_customer_orders",
                    {"customer_id": 1},
                )
            ]
        ),
        audit_log=audit_log,
    )

    response = runtime.run(context=context, message="Show my orders", session=db_session)
    event = audit_log.events[-1]
    projection = get_projection_store().get_run(response.agent_run_id)

    assert event.request_id == context.request_id
    assert event.actor_id == context.principal.actor_id
    assert event.actor_type == context.principal.actor_type
    assert event.roles == context.principal.roles
    assert event.effective_customer_id == context.effective_customer_id
    assert projection is not None
    assert projection.request_id == context.request_id
    assert projection.actor_id == context.principal.actor_id
    assert projection.actor_type == context.principal.actor_type.value
    assert projection.roles == context.principal.roles
    serialized = context.model_dump(mode="json")
    assert "credential_id" not in str(serialized)
    assert "safe-credential-reference" not in repr(context)
