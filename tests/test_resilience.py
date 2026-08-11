from collections.abc import Sequence

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.agent.tool_catalog import TOOL_DEFINITIONS, AgentToolDefinition
from app.core.context import ExecutionContext
from app.models import Order
from app.models.entities import OrderStatus
from app.policies.engine import PolicyEngine
from app.policies.models import PolicyDecision
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.reranking.service import Reranker
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.schemas import DocumentChunk
from app.resilience.classification import classify_failure, is_retryable
from app.resilience.config import ResilienceConfig
from app.resilience.errors import (
    FailureCategory,
    ResilienceError,
    UnknownWriteOutcomeError,
)
from app.resilience.retry import run_with_retry
from app.services.idempotency import IdempotencyScope


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
        reason="resilience test",
    )


def config() -> ResilienceConfig:
    return ResilienceConfig(max_retries=2, initial_backoff_ms=0, max_backoff_ms=0)


def test_failure_classification_does_not_retry_domain_errors() -> None:
    error = ValueError("invalid state")
    assert classify_failure(error, dependency="tool") == FailureCategory.TOOL_PERMANENT_FAILURE
    assert is_retryable(FailureCategory.TOOL_PERMANENT_FAILURE) is False


def test_retry_is_bounded_and_does_not_sleep_for_tests() -> None:
    calls = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("temporary")

    try:
        run_with_retry(
            operation,
            dependency="retrieval",
            config=config(),
            sleeper=sleeps.append,
            timeout_seconds=1.0,
        )
    except Exception as error:
        assert isinstance(error, ResilienceError)
        assert error.category == FailureCategory.RETRIEVAL_TIMEOUT
    assert calls == 3
    assert sleeps == [0.0, 0.0]


def test_native_timeout_retry_attempts_never_overlap() -> None:
    active_call_count = 0
    max_concurrent_calls = 0
    events: list[str] = []
    attempts = 0

    def native_dependency_call() -> None:
        nonlocal active_call_count, max_concurrent_calls, attempts
        attempts += 1
        active_call_count += 1
        max_concurrent_calls = max(max_concurrent_calls, active_call_count)
        events.append(f"start:{attempts}")
        try:
            raise TimeoutError("dependency-native timeout")
        finally:
            active_call_count -= 1
            events.append(f"end:{attempts}")

    with pytest.raises(ResilienceError):
        run_with_retry(
            native_dependency_call,
            dependency="retrieval",
            config=ResilienceConfig(max_retries=1, initial_backoff_ms=0, max_backoff_ms=0),
            timeout_seconds=0.01,
            sleeper=lambda _: None,
        )

    assert max_concurrent_calls == 1
    assert events == ["start:1", "end:1", "start:2", "end:2"]


def test_retry_total_budget_is_bounded_with_a_controllable_clock() -> None:
    now = 0.0
    attempts = 0

    def clock() -> float:
        return now

    def timeout() -> None:
        nonlocal now, attempts
        attempts += 1
        now += 2.0
        raise TimeoutError("native timeout")

    def sleeper(delay: float) -> None:
        nonlocal now
        now += delay

    with pytest.raises(ResilienceError) as raised:
        run_with_retry(
            timeout,
            dependency="retrieval",
            config=ResilienceConfig(max_retries=3, initial_backoff_ms=100, max_backoff_ms=100),
            timeout_seconds=2.0,
            clock=clock,
            sleeper=sleeper,
        )

    assert attempts == 4
    assert now <= 8.3
    assert raised.value.category == FailureCategory.RETRIEVAL_TIMEOUT


def test_unknown_write_outcome_is_never_retried_even_if_mislabeled_as_read() -> None:
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise UnknownWriteOutcomeError("request_refund")

    with pytest.raises(UnknownWriteOutcomeError):
        run_with_retry(operation, dependency="tool", operation_type="read", config=config())

    assert calls == 1


def test_read_tool_retries_once_then_executes(db_session: Session) -> None:
    original = TOOL_DEFINITIONS["get_customer_orders"]
    calls = 0

    def flaky(
        session: Session,
        context: ExecutionContext,
        request: BaseModel,
        idempotency: IdempotencyScope | None,
    ) -> object:
        del idempotency
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary read timeout")
        return original.execute(session, context, request, None)

    TOOL_DEFINITIONS["get_customer_orders"] = AgentToolDefinition(original.input_model, flaky)
    try:
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
            resilience_config=config(),
        )
        result = runtime.run(
            conversation_id="retry-read",
            customer_id=1,
            message="Show my orders.",
            session=db_session,
        )
    finally:
        TOOL_DEFINITIONS["get_customer_orders"] = original
    assert calls == 2
    assert result.tool_call is not None
    assert result.tool_call.status == "executed"


def test_policy_failure_fails_closed_without_pending_or_mutation(db_session: Session) -> None:
    class BrokenPolicy(PolicyEngine):
        def evaluate(
            self,
            *,
            tool_name: str,
            context: ExecutionContext,
            arguments: dict[str, object],
        ) -> PolicyDecision:
            raise RuntimeError("policy unavailable")

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
        policy_engine=BrokenPolicy(),
        resilience_config=config(),
    )
    result = runtime.run(
        conversation_id="policy-fail-closed",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    order = db_session.get(Order, 3)
    assert result.pending_action is None
    assert result.tool_call is None
    assert result.failure_category == "policy_failure"
    assert order is not None and OrderStatus(order.status) == OrderStatus.PENDING


def test_confirmation_executes_without_second_llm_call(db_session: Session) -> None:
    class OneDecisionThenUnavailable:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, **kwargs: object) -> StructuredDecision:
            self.calls += 1
            if self.calls > 1:
                raise ConnectionError("LLM unavailable")
            return decision(
                Intent.ORDER_CANCEL,
                AgentRequestType.WRITE_ACTION,
                "cancel_order",
                {"customer_id": 1, "order_id": 3},
            )

    provider = OneDecisionThenUnavailable()
    runtime = AgentRuntime(provider=provider, resilience_config=config())
    runtime.run(
        conversation_id="confirmation-no-llm",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    result = runtime.run(
        conversation_id="confirmation-no-llm",
        customer_id=1,
        message="Yes",
        session=db_session,
    )
    assert provider.calls == 1
    assert result.tool_call is not None
    assert result.tool_call.status == "executed"


def test_unknown_write_outcome_is_not_replayed(db_session: Session) -> None:
    original = TOOL_DEFINITIONS["cancel_order"]

    def unknown(
        session: Session,
        context: ExecutionContext,
        request: BaseModel,
        idempotency: IdempotencyScope | None,
    ) -> object:
        del session, context, request, idempotency
        raise UnknownWriteOutcomeError("cancel_order")

    TOOL_DEFINITIONS["cancel_order"] = AgentToolDefinition(original.input_model, unknown)
    try:
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
            resilience_config=config(),
            checkpointer=MemorySaver(),
        )
        runtime.run(
            conversation_id="unknown-write",
            customer_id=1,
            message="Cancel order 3.",
            session=db_session,
        )
        result = runtime.run(
            conversation_id="unknown-write",
            customer_id=1,
            message="Yes",
            session=db_session,
        )
        repeated = runtime.run(
            conversation_id="unknown-write",
            customer_id=1,
            message="Yes",
            session=db_session,
        )
    finally:
        TOOL_DEFINITIONS["cancel_order"] = original
    assert result.write_outcome_unknown is True
    assert "won't repeat" in result.message
    assert repeated.tool_call is None


class BrokenReranker(Reranker):
    def score(self, query: str, chunks: Sequence[object]) -> list[float]:
        raise RuntimeError("reranker unavailable")


def test_reranker_failure_degrades_to_fused_results() -> None:
    retriever = HybridRetriever(
        DeterministicEmbeddingProvider(), reranker=BrokenReranker(), final_context_count=1
    )
    retriever.upsert(
        [
            DocumentChunk(
                chunk_id="refund#eligibility#0",
                document_id="refund",
                title="Refund",
                category="refund",
                section="eligibility",
                source="knowledge/refund.md",
                chunk_index=0,
                content="Delivered orders may qualify for review.",
            )
        ]
    )
    results = retriever.retrieve("delivered refund")
    assert results
    assert retriever.last_degraded_components == ["reranker"]
