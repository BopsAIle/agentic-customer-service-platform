import json
from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from typing import cast

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, AgentResponse, Intent, StructuredDecision
from app.agent.state import AgentState
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.models.entities import AgentRunProjectionRecord, Order, OrderStatus
from app.ui.projection import get_projection_store
from app.ui.repository import (
    InMemoryAgentRunProjectionRepository,
    SqlAlchemyAgentRunProjectionRepository,
)
from app.ui.schemas import AgentRunView, UIMemoryUsage, UIRetrievalMetadata


def projection(
    run_id: str,
    *,
    customer_id: int = 1,
    started_at: datetime | None = None,
    status: str = "completed",
) -> AgentRunView:
    return AgentRunView(
        run_id=run_id,
        request_id=f"request-{run_id}",
        conversation_id=f"conversation-{customer_id}",
        action_id=None,
        customer_id=customer_id,
        actor_id=f"actor-{customer_id}",
        actor_type="support_operator",
        roles=["support_operator"],
        intent="order_list",
        request_type="read_action",
        status=status,
        started_at=started_at or datetime.now(UTC),
        duration_ms=12.5,
        trace_id=None,
        path=["understand_request", "respond"],
        memory=UIMemoryUsage(item_count=0),
        retrieval_metadata=UIRetrievalMetadata(),
        answer_grounding={
            "status": "pass",
            "sources_used": 1,
            "citation_count": 1,
            "citation_coverage": 1.0,
            "unsupported_claim_count": 0,
            "confidence": 0.9,
            "accepted": True,
        },
    )


def test_sql_projection_upsert_is_durable_and_preserves_created_at(
    db_session: Session,
) -> None:
    repository = SqlAlchemyAgentRunProjectionRepository(db_session)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    first = projection("run-durable", started_at=started_at, status="pending").model_copy(
        update={"action_id": "action-durable"}
    )
    repository.upsert(first)
    record = db_session.scalar(
        select(AgentRunProjectionRecord).where(AgentRunProjectionRecord.run_id == first.run_id)
    )
    assert record is not None
    created_at = record.created_at

    repository.upsert(first.model_copy(update={"status": "completed", "duration_ms": 20.0}))
    second = SqlAlchemyAgentRunProjectionRepository(db_session).get_by_run_id(first.run_id)

    assert second is not None
    assert second.status == "completed"
    assert second.action_id == "action-durable"
    assert second.duration_ms == 20.0
    assert second.answer_grounding.status == "pass"
    assert second.answer_grounding.citation_coverage == 1.0
    assert record.created_at == created_at
    assert record.updated_at > created_at
    assert db_session.query(AgentRunProjectionRecord).count() == 1


def test_sql_projection_is_visible_to_an_independent_repository_instance(
    db_session: Session,
) -> None:
    repository = SqlAlchemyAgentRunProjectionRepository(db_session)
    repository.upsert(projection("run-worker-a"))
    independent = SqlAlchemyAgentRunProjectionRepository(Session(bind=db_session.get_bind()))

    visible = independent.get_by_run_id("run-worker-a")

    assert visible is not None
    assert visible.run_id == "run-worker-a"
    independent.session.close()


def test_projection_queries_are_bounded_isolated_and_deterministic(db_session: Session) -> None:
    repository = SqlAlchemyAgentRunProjectionRepository(db_session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(125):
        repository.upsert(
            projection(
                f"run-{index:03d}",
                customer_id=1 if index % 2 else 2,
                started_at=base + timedelta(seconds=index),
            )
        )

    recent = repository.list_recent(limit=500)
    default_recent = repository.list_recent()
    customer_one = repository.list_for_customer(1, limit=500)
    conversation = repository.list_for_conversation("conversation-1", limit=500)

    assert len(recent) == 100
    assert len(default_recent) == 50
    assert [run.run_id for run in recent[:3]] == ["run-124", "run-123", "run-122"]
    assert all(run.customer_id == 1 for run in customer_one)
    assert [run.run_id for run in conversation[:2]] == ["run-001", "run-003"]


def test_in_memory_projection_adapter_is_bounded_and_thread_safe() -> None:
    repository = InMemoryAgentRunProjectionRepository(max_projections=3)
    barrier = Barrier(8)

    def write(index: int) -> None:
        barrier.wait()
        repository.upsert(projection(f"memory-{index:02d}"))

    threads = [Thread(target=write, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    recent = repository.list_recent(limit=100)
    assert len(recent) == 3
    assert len({run.run_id for run in recent}) == 3


def test_projection_failure_does_not_replay_or_undo_committed_business_write(
    db_session: Session,
) -> None:
    class FailingProjectionRepository:
        def upsert(self, projection: AgentRunView) -> None:
            del projection
            raise RuntimeError("projection database unavailable")

    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                StructuredDecision(
                    intent=Intent.ORDER_CANCEL,
                    request_type=AgentRequestType.WRITE_ACTION,
                    tool_name="cancel_order",
                    arguments={"customer_id": 1, "order_id": 3},
                    reason="projection failure test",
                )
            ]
        ),
        checkpointer=MemorySaver(),
        projection_repository=FailingProjectionRepository(),  # type: ignore[arg-type]
    )

    pending = runtime.run(
        conversation_id="projection-failure",
        customer_id=1,
        message="Cancel order 3",
        session=db_session,
    )
    response = runtime.run(
        conversation_id="projection-failure",
        customer_id=1,
        message="confirm",
        session=db_session,
    )

    order = db_session.get(Order, 3)
    assert pending.pending_action is not None
    assert response.tool_call is not None
    assert response.tool_call.status == "executed"
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.CANCELLED


def test_projection_row_excludes_prompt_memory_credential_and_tool_argument_sentinels(
    db_session: Session,
) -> None:
    prompt = "PROMPT_SENTINEL_DO_NOT_PERSIST"
    memory = "RAW_MEMORY_SENTINEL_DO_NOT_PERSIST"
    credential = "Bearer PROJECTION_CREDENTIAL_SENTINEL"
    tool_argument = "SENSITIVE_TOOL_ARGUMENT_SENTINEL"
    store = get_projection_store()
    context = ExecutionContext(
        request_id="projection-safe-request",
        conversation_id="projection-safe-conversation",
        principal=Principal(
            actor_id="projection-safe-operator",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )
    response = AgentResponse(
        conversation_id=context.conversation_id,
        agent_run_id="projection-safe-run",
        message="safe response",
        intent=Intent.ORDER_LIST,
        request_type=AgentRequestType.READ_ACTION,
    )
    state = {
        "messages": [{"role": "user", "content": prompt}],
        "authorization": {"authorization": credential},
        "decision": {"arguments": {"secret": tool_argument}},
        "memory_context": [{"content": memory, "normalized_key": "response_style"}],
        "tool_result": {"secret": tool_argument, "safe_field": "value"},
        "retrieval_metadata": {},
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=context,
        trace_id=None,
    ) as captured:
        view = store.build_view(
            captured,
            response=response,
            state=cast(AgentState, state),
            policy_events=[],
            duration_ms=1.0,
        )
    SqlAlchemyAgentRunProjectionRepository(db_session).upsert(view)
    record = db_session.scalar(
        select(AgentRunProjectionRecord).where(
            AgentRunProjectionRecord.run_id == response.agent_run_id
        )
    )
    assert record is not None
    serialized = json.dumps(
        {key: value for key, value in vars(record).items() if key != "_sa_instance_state"},
        default=str,
        sort_keys=True,
    )
    for sentinel in (prompt, memory, credential, tool_argument):
        assert sentinel not in serialized
