import time
from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import qdrant_client
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.core import database
from app.core.config import Settings
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.reranking.service import Reranker
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.schemas import DocumentChunk, RetrievedChunk
from app.rag.storage.qdrant import QdrantKnowledgeStore
from app.resilience.config import ResilienceConfig


def decision(*, requires_retrieval: bool = False) -> StructuredDecision:
    return StructuredDecision(
        intent=Intent.REFUND_POLICY if requires_retrieval else Intent.CAPABILITY_QUESTION,
        request_type=(
            AgentRequestType.KNOWLEDGE_ONLY
            if requires_retrieval
            else AgentRequestType.INFORMATIONAL
        ),
        reason="timeout test",
        requires_retrieval=requires_retrieval,
        knowledge_query="refund policy" if requires_retrieval else None,
    )


class SlowDecisionProvider:
    def decide(self, **kwargs: object) -> StructuredDecision:
        del kwargs
        time.sleep(0.1)
        return decision()


class SlowRetriever:
    def retrieve(self, query: str) -> list[RetrievedChunk]:
        del query
        time.sleep(0.1)
        return []


class SlowReranker(Reranker):
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        del query
        time.sleep(0.1)
        return [1.0 for _ in chunks]


def timeout_config() -> ResilienceConfig:
    return ResilienceConfig(
        max_retries=0,
        initial_backoff_ms=0,
        max_backoff_ms=0,
        llm_timeout_seconds=0.01,
        retrieval_timeout_seconds=0.01,
        reranker_timeout_seconds=0.01,
    )


def test_llm_invocation_timeout_is_enforced(db_session: Session) -> None:
    result = AgentRuntime(provider=SlowDecisionProvider(), resilience_config=timeout_config()).run(
        conversation_id="llm-timeout",
        customer_id=1,
        message="Help",
        session=db_session,
    )

    assert result.error_category == "llm_error"
    assert result.failure_category == "llm_timeout"


def test_retrieval_timeout_is_enforced(db_session: Session) -> None:
    result = AgentRuntime(
        provider=FakeDecisionProvider([decision(requires_retrieval=True)]),
        knowledge_retriever=SlowRetriever(),
        resilience_config=timeout_config(),
    ).run(
        conversation_id="retrieval-timeout",
        customer_id=1,
        message="What is the refund policy?",
        session=db_session,
    )

    assert result.error_category == "retrieval_error"
    assert result.failure_category == "retrieval_timeout"


def test_reranker_timeout_degrades_to_fused_results() -> None:
    retriever = HybridRetriever(
        DeterministicEmbeddingProvider(),
        reranker=SlowReranker(),
        final_context_count=1,
        reranker_timeout_seconds=0.01,
    )
    retriever.upsert(
        [
            DocumentChunk(
                chunk_id="refund#timeout#0",
                document_id="refund",
                title="Refund",
                category="refund",
                section="timeout",
                source="knowledge/refund.md",
                chunk_index=0,
                content="Delivered orders can be reviewed for refunds.",
            )
        ]
    )

    assert retriever.retrieve("refund")
    assert retriever.last_degraded_components == ["reranker"]


def test_llm_http_client_has_explicit_connect_and_request_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def with_structured_output(self, schema: object) -> object:
            del schema
            return object()

    monkeypatch.setattr("app.agent.llm.provider.ChatOpenAI", FakeChatOpenAI)
    OpenAICompatibleProvider(Settings(llm_connect_timeout_seconds=1.5, llm_timeout_seconds=7.0))

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 1.5
    assert timeout.read == 7.0
    assert timeout.write == 7.0
    assert captured["max_retries"] == 0


def test_qdrant_http_client_has_an_explicit_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeQdrantClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(qdrant_client, "QdrantClient", FakeQdrantClient)
    QdrantKnowledgeStore(
        "http://qdrant.test",
        "knowledge",
        DeterministicEmbeddingProvider(),
        timeout_seconds=2.2,
    )

    assert captured["timeout"] == 3


def test_postgres_engine_has_explicit_connect_pool_and_query_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> Engine:
        captured["url"] = url
        captured.update(kwargs)
        return cast(Engine, object())

    settings = Settings(
        database_url="postgresql+psycopg://app:app@db:5432/customer_service",
        database_connect_timeout_seconds=2.1,
        database_query_timeout_seconds=4.2,
        database_pool_timeout_seconds=1.5,
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "create_engine", fake_create_engine)

    database.build_engine()

    assert captured["pool_timeout"] == 1.5
    connect_args = cast(dict[str, object], captured["connect_args"])
    assert connect_args["connect_timeout"] == 3
    assert connect_args["options"] == "-c statement_timeout=4200"
