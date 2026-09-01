from collections.abc import Callable

from app.agent.cskh import knowledge_queries_for
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.rag.answer_generator import GroundedAnswerGenerator, normalize_knowledge_query
from app.rag.interfaces import KnowledgeRetriever
from app.rag.schemas import RetrievedChunk
from app.resilience.config import ResilienceConfig
from app.resilience.control import ReliabilityController
from app.resilience.errors import ResilienceError, RetryExhaustedError
from app.resilience.fallbacks import degraded_message
from app.resilience.retry import run_with_retry


def make_retrieve_node(
    retriever: KnowledgeRetriever,
    generator: GroundedAnswerGenerator,
    resilience_config: ResilienceConfig | None = None,
    reliability_controller: ReliabilityController | None = None,
) -> Callable[[AgentState], AgentState]:
    def retrieve_knowledge(state: AgentState) -> AgentState:
        if state.get("error_category") == AgentErrorCategory.RESOURCE_NOT_FOUND and state.get(
            "proposed_write"
        ):
            state = {**state, "error_category": None, "last_error": None}

        order_status = _order_status(state)
        queries = [
            normalize_knowledge_query(query)
            for query in knowledge_queries_for(
                intent=state.get("intent"),
                situation=state.get("situation"),
                order_status=order_status,
                compiler_query=state.get("knowledge_query"),
            )
        ]
        timeout_seconds = (resilience_config or ResilienceConfig()).retrieval_timeout_seconds
        chunks: list[RetrievedChunk] = []
        retrieval_metadata: dict[str, object] = {}
        degraded: list[str] = []
        try:
            for query in queries:
                retrieval = run_with_retry(
                    lambda current=query: retriever.retrieve(current),
                    dependency="retrieval",
                    config=resilience_config,
                    controller=reliability_controller,
                    service_identity=f"retrieval:{type(retriever).__name__}",
                    timeout_seconds=timeout_seconds,
                )
                chunks.extend(retrieval.chunks)
                degraded.extend(retrieval.degraded_components)
                metadata = retrieval.metadata
                retrieval_metadata = {
                    "backend": metadata.backend,
                    "embedding_provider": metadata.embedding_provider,
                    "reranker_enabled": metadata.reranker_enabled,
                    "retrieval_count": metadata.retrieval_count,
                    "latency_seconds": metadata.latency_seconds,
                    "fallback_status": metadata.fallback_status,
                    "hybrid": metadata.hybrid,
                    "fusion_strategy": metadata.fusion_strategy,
                    "dense_candidate_count": metadata.dense_candidate_count,
                    "sparse_candidate_count": metadata.sparse_candidate_count,
                    "query_count": len(queries),
                }
        except (RetryExhaustedError, ResilienceError) as error:
            knowledge_only = state.get("tool_result") is None
            fallback = degraded_message(error.category, knowledge_only=knowledge_only)
            if knowledge_only:
                return {
                    "last_error": fallback,
                    "error_category": AgentErrorCategory.RETRIEVAL_ERROR,
                    "failure_category": error.category.value,
                    "recovery_action": "degraded",
                    "degraded_components": ["retrieval"],
                    "answer_grounding": _unavailable_grounding(),
                }
            return {
                "knowledge_answer": fallback,
                "failure_category": error.category.value,
                "recovery_action": "degraded",
                "degraded_components": ["retrieval"],
                "answer_grounding": _unavailable_grounding(),
            }

        unique_chunks = _dedupe_chunks(chunks)
        grounding_query = queries[0] if queries else "support policy"
        grounded = generator.answer(grounding_query, unique_chunks)
        return {
            "retrieved_chunks": [chunk.model_dump(mode="json") for chunk in unique_chunks],
            "retrieval_metadata": retrieval_metadata,
            "knowledge_answer": grounded.answer,
            "citations": [citation.model_dump(mode="json") for citation in grounded.citations],
            "answer_grounding": {
                "status": grounded.status.value,
                "sources_used": grounded.source_count,
                "citation_count": len(grounded.citations),
                "citation_coverage": grounded.validation.citation_coverage,
                "unsupported_claim_count": len(grounded.unsupported_claims),
                "confidence": grounded.confidence,
                "accepted": grounded.validation.accepted,
            },
            "degraded_components": list(dict.fromkeys(degraded)),
            "recovery_action": "degraded" if degraded else None,
            "error_category": None if state.get("proposed_write") else state.get("error_category"),
        }

    return retrieve_knowledge


def _order_status(state: AgentState) -> str | None:
    tool_result = state.get("tool_result") or {}
    status = tool_result.get("status")
    return status if isinstance(status, str) else None


def _dedupe_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: set[str] = set()
    unique: list[RetrievedChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        unique.append(chunk)
    return unique


def _unavailable_grounding() -> dict[str, object]:
    return {
        "status": "retrieval_unavailable",
        "sources_used": 0,
        "citation_count": 0,
        "citation_coverage": 0.0,
        "unsupported_claim_count": 0,
        "confidence": 0.0,
        "accepted": False,
    }
