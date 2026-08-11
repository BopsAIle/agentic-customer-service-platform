from concurrent.futures import ThreadPoolExecutor

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.auth.models import ActorType, Principal
from app.core.config import Settings
from app.core.context import ExecutionContext
from app.memory.service import MemoryService
from app.models import Order
from app.models.entities import OrderStatus
from app.persistence.checkpoint import (
    CheckpointBackend,
    MemoryCheckpointProvider,
    build_checkpoint_provider,
    checkpoint_thread_id,
    checkpoint_thread_id_hash,
)
from app.policies.models import PendingActionStatus


def execution_context(
    *,
    actor_id: str = "customer-one",
    customer_id: int = 1,
    conversation_id: str = "durable-thread",
) -> ExecutionContext:
    return ExecutionContext(
        request_id=f"request-{actor_id}-{customer_id}",
        conversation_id=conversation_id,
        principal=Principal(
            actor_id=actor_id,
            actor_type=ActorType.CUSTOMER,
            roles=["customer"],
            customer_id=customer_id,
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
        reason="checkpoint persistence test",
    )


def informational_decision() -> StructuredDecision:
    return decision(Intent.CAPABILITY_QUESTION, AgentRequestType.INFORMATIONAL)


def test_thread_identity_contains_all_authoritative_scope_fields() -> None:
    context = execution_context(
        actor_id="customer:one",
        customer_id=17,
        conversation_id="shared:conversation",
    )

    thread_id = checkpoint_thread_id(context)

    assert thread_id == ("v1:customer:customer%3Aone:customer-17:shared%3Aconversation")
    assert checkpoint_thread_id_hash(context) == checkpoint_thread_id_hash(context)
    assert len(checkpoint_thread_id_hash(context)) == 16


def test_test_configuration_builds_an_in_memory_provider() -> None:
    provider = build_checkpoint_provider(Settings(checkpoint_backend="memory"))

    assert isinstance(provider, MemoryCheckpointProvider)
    assert provider.backend == CheckpointBackend.MEMORY


def test_same_thread_resumes_after_runtime_restart_simulation(db_session: Session) -> None:
    checkpoint_provider = MemoryCheckpointProvider()
    context = execution_context(conversation_id="restart-resume")
    first_provider = FakeDecisionProvider([informational_decision()])
    first_runtime = AgentRuntime(
        provider=first_provider,
        checkpointer=checkpoint_provider.checkpointer,
    )
    first_runtime.run(context=context, message="First request", session=db_session)

    second_provider = FakeDecisionProvider([informational_decision()])
    restarted_runtime = AgentRuntime(
        provider=second_provider,
        checkpointer=checkpoint_provider.checkpointer,
    )
    restarted_runtime.run(context=context, message="Second request", session=db_session)

    resumed_messages = [message["content"] for message in second_provider.calls[0]]
    assert resumed_messages[0] == "First request"
    assert resumed_messages[-1] == "Second request"


def test_pending_action_survives_restart_and_confirmation_executes(
    db_session: Session,
) -> None:
    checkpoint_provider = MemoryCheckpointProvider()
    context = execution_context(conversation_id="restart-confirmation")
    first_runtime = AgentRuntime(
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
        checkpointer=checkpoint_provider.checkpointer,
    )
    pending = first_runtime.run(
        context=context,
        message="Cancel order 3",
        session=db_session,
    )

    restarted_runtime = AgentRuntime(
        provider=FakeDecisionProvider([]),
        checkpointer=checkpoint_provider.checkpointer,
    )
    confirmed = restarted_runtime.run(context=context, message="yes", session=db_session)

    order = db_session.get(Order, 3)
    assert pending.pending_action is not None
    assert pending.pending_action.status == PendingActionStatus.PENDING
    assert confirmed.pending_action is not None
    assert confirmed.pending_action.status == PendingActionStatus.EXECUTED
    assert confirmed.pending_action.action_id == pending.pending_action.action_id
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.CANCELLED


def test_wrong_actor_cannot_confirm_action_after_restart(db_session: Session) -> None:
    checkpoint_provider = MemoryCheckpointProvider()
    owner_context = execution_context(
        actor_id="customer-owner",
        conversation_id="wrong-actor-confirmation",
    )
    first_runtime = AgentRuntime(
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
        checkpointer=checkpoint_provider.checkpointer,
    )
    first_runtime.run(context=owner_context, message="Cancel order 3", session=db_session)

    wrong_actor_runtime = AgentRuntime(
        provider=FakeDecisionProvider([]),
        checkpointer=checkpoint_provider.checkpointer,
    )
    attempted = wrong_actor_runtime.run(
        context=execution_context(
            actor_id="customer-attacker",
            conversation_id="wrong-actor-confirmation",
        ),
        message="yes",
        session=db_session,
    )

    order = db_session.get(Order, 3)
    assert attempted.pending_action is None
    assert attempted.tool_call is None
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.PENDING


def test_different_actors_with_same_conversation_id_are_isolated(db_session: Session) -> None:
    checkpointer = MemorySaver()
    first_runtime = AgentRuntime(
        provider=FakeDecisionProvider([informational_decision()]),
        checkpointer=checkpointer,
    )
    first_runtime.run(
        context=execution_context(actor_id="actor-one", conversation_id="shared-conversation"),
        message="Actor one request",
        session=db_session,
    )
    second_provider = FakeDecisionProvider([informational_decision()])
    second_runtime = AgentRuntime(provider=second_provider, checkpointer=checkpointer)
    second_runtime.run(
        context=execution_context(actor_id="actor-two", conversation_id="shared-conversation"),
        message="Actor two request",
        session=db_session,
    )

    assert [message["content"] for message in second_provider.calls[0]] == ["Actor two request"]


def test_concurrent_customer_contexts_do_not_share_state(db_session: Session) -> None:
    checkpointer = MemorySaver()

    def run_customer(actor_id: str, customer_id: int) -> list[str]:
        provider = FakeDecisionProvider([informational_decision()])
        runtime = AgentRuntime(
            provider=provider,
            checkpointer=checkpointer,
            memory_service=MemoryService(enabled=False),
        )
        runtime.run(
            context=execution_context(
                actor_id=actor_id,
                customer_id=customer_id,
                conversation_id="concurrent-conversation",
            ),
            message=f"Request from {actor_id}",
            session=db_session,
        )
        return [message["content"] for message in provider.calls[0]]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_customer, "customer-one", 1)
        second = executor.submit(run_customer, "customer-two", 2)

    assert first.result() == ["Request from customer-one"]
    assert second.result() == ["Request from customer-two"]
