from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.models import Order
from app.models.entities import OrderStatus
from app.policies.models import stable_policy_event_id
from app.policies.repository import InMemoryPolicyAuditLog
from app.ui.repository import InMemoryAgentRunProjectionRepository


def _context(request_id: str, *, actor_id: str = "operator-one") -> ExecutionContext:
    return ExecutionContext(
        request_id=request_id,
        conversation_id="identity-conversation",
        principal=Principal(
            actor_id=actor_id,
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )


def _cancel_decision() -> StructuredDecision:
    return StructuredDecision(
        intent=Intent.ORDER_CANCEL,
        request_type=AgentRequestType.WRITE_ACTION,
        tool_name="cancel_order",
        arguments={"customer_id": 1, "order_id": 3},
        reason="invocation identity test",
    )


def test_confirmation_creates_new_invocation_but_preserves_action_lifecycle(
    db_session: Session,
) -> None:
    checkpoint = MemorySaver()
    audit = InMemoryPolicyAuditLog()
    projections = InMemoryAgentRunProjectionRepository()
    initial_runtime = AgentRuntime(
        provider=FakeDecisionProvider([_cancel_decision()]),
        checkpointer=checkpoint,
        audit_log=audit,
        projection_repository=projections,
    )
    confirmation_runtime = AgentRuntime(
        provider=FakeDecisionProvider([]),
        checkpointer=checkpoint,
        audit_log=audit,
        projection_repository=projections,
    )

    pending = initial_runtime.run(
        context=_context("request-initial"),
        message="Cancel order 3",
        session=db_session,
    )
    confirmed = confirmation_runtime.run(
        context=_context("request-confirmation"),
        message="yes",
        session=db_session,
    )

    assert pending.pending_action is not None
    assert confirmed.pending_action is not None
    assert pending.agent_run_id != confirmed.agent_run_id
    assert pending.conversation_id == confirmed.conversation_id
    assert pending.pending_action.action_id == confirmed.pending_action.action_id
    assert OrderStatus(db_session.get(Order, 3).status) == OrderStatus.CANCELLED  # type: ignore[union-attr]

    initial_view = projections.get_by_run_id(pending.agent_run_id)
    confirmation_view = projections.get_by_run_id(confirmed.agent_run_id)
    assert initial_view is not None
    assert confirmation_view is not None
    assert initial_view.run_id != confirmation_view.run_id
    assert initial_view.request_id == "request-initial"
    assert confirmation_view.request_id == "request-confirmation"
    assert initial_view.conversation_id == confirmation_view.conversation_id
    assert initial_view.action_id == confirmation_view.action_id == pending.pending_action.action_id
    assert initial_view.status == "waiting_confirmation"
    assert confirmation_view.status == "completed"
    assert initial_view.path != confirmation_view.path
    assert initial_view.duration_ms >= 0
    assert confirmation_view.duration_ms >= 0

    lifecycle_events = [
        event for event in audit.events if event.action_id == initial_view.action_id
    ]
    assert [event.stage for event in lifecycle_events] == [
        "policy_evaluation",
        "confirmation",
        "policy_revalidation",
        "execution",
        "execution",
    ]
    assert lifecycle_events[0].agent_run_id == initial_view.run_id
    assert all(event.agent_run_id == confirmation_view.run_id for event in lifecycle_events[1:])


def test_confirmation_replay_gets_new_run_without_replaying_action(
    db_session: Session,
) -> None:
    checkpoint = MemorySaver()
    projections = InMemoryAgentRunProjectionRepository()
    audit = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_cancel_decision()]),
        checkpointer=checkpoint,
        audit_log=audit,
        projection_repository=projections,
    )

    pending = runtime.run(
        context=_context("request-1"), message="Cancel order 3", session=db_session
    )
    confirmed = runtime.run(context=_context("request-2"), message="yes", session=db_session)
    replay = runtime.run(context=_context("request-3"), message="yes", session=db_session)

    assert pending.pending_action is not None
    assert confirmed.pending_action is not None
    assert replay.agent_run_id not in {pending.agent_run_id, confirmed.agent_run_id}
    assert replay.pending_action is not None
    assert replay.pending_action.action_id == pending.pending_action.action_id
    assert replay.tool_call is None
    assert len(projections.list_for_conversation("identity-conversation", limit=100)) == 3
    assert db_session.query(Order).filter(Order.id == 3).one().status == OrderStatus.CANCELLED
    assert len([event for event in audit.events if event.stage == "execution"]) == 2


def test_action_lifecycle_event_identity_is_stable_across_invocations() -> None:
    assert stable_policy_event_id("run-a", "action-a", "execution", "success") == (
        stable_policy_event_id("run-b", "action-a", "execution", "success")
    )
    assert stable_policy_event_id("run-a", None, "execution", "success") != (
        stable_policy_event_id("run-b", None, "execution", "success")
    )
