from collections.abc import Sequence
from types import SimpleNamespace
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
from app.rag.interfaces import RetrievalResult
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
        raise httpx.ReadTimeout("native LLM request deadline")


class SlowRetriever:
    def retrieve(self, query: str) -> RetrievalResult:
        del query
        raise TimeoutError("native retrieval request deadline")


class SlowReranker(Reranker):
    def score(self, query: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        del query, chunks
        raise TimeoutError("native reranker deadline")


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

    result = retriever.retrieve("refund")
    assert result.chunks
    assert result.degraded_components == ("reranker",)


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

    assert captured["timeout"] == 2


def test_qdrant_request_uses_native_timeout_before_retry() -> None:
    events: list[str] = []
    calls = 0

    class FakeClient:
        def get_collection(self, name: str) -> SimpleNamespace:
            del name
            return SimpleNamespace(
                config=SimpleNamespace(
                    metadata={
                        "lexical_index": {
                            "version": 1,
                            "vocabulary": {"refund": 1},
                            "inverse_document_frequency": {"refund": 1.0},
                            "average_document_length": 1.0,
                            "document_count": 1,
                        }
                    }
                )
            )

        def query_points(self, **kwargs: object) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            events.append(f"start:{calls}:{kwargs['timeout']}")
            try:
                if calls == 1:
                    raise TimeoutError("qdrant native timeout")
                return SimpleNamespace(points=[])
            finally:
                events.append(f"end:{calls}")

    from app.rag.backends.qdrant import QdrantKnowledgeBackend

    backend = QdrantKnowledgeBackend(
        url="http://qdrant.test",
        collection_name="knowledge",
        embedding_provider=DeterministicEmbeddingProvider(),
        reranker=None,
        reranker_enabled=False,
        rerank_candidates=4,
        final_context_count=2,
        timeout_seconds=1.5,
        reranker_timeout_seconds=0.1,
        client=FakeClient(),
    )

    from app.resilience.config import ResilienceConfig
    from app.resilience.retry import run_with_retry

    result = run_with_retry(
        lambda: backend.retrieve("refund"),
        dependency="retrieval",
        config=ResilienceConfig(max_retries=1, initial_backoff_ms=0, max_backoff_ms=0),
        timeout_seconds=1.5,
        sleeper=lambda _: None,
    )

    assert result.chunks == ()
    assert events == ["start:1:1", "end:1", "start:2:1", "end:2"]


def test_openai_embedding_client_has_native_timeout_and_no_hidden_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def embed_query(self, text: str) -> list[float]:
            del text
            return [1.0]

    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", FakeEmbeddings)
    from app.rag.embeddings.providers import OpenAIEmbeddingProvider

    provider = OpenAIEmbeddingProvider(
        model="embedding-model",
        api_key=None,
        base_url="http://embedding.test/v1",
        connect_timeout_seconds=1.5,
        timeout_seconds=7.0,
    )
    provider.embed_query("refund")

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 1.5
    assert timeout.read == 7.0
    assert timeout.write == 7.0
    assert captured["max_retries"] == 0


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
