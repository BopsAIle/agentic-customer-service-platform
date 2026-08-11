from collections.abc import Callable

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.rag.generation.grounded import GroundedAnswerGenerator
from app.rag.interfaces import KnowledgeRetriever
from app.resilience.config import ResilienceConfig
from app.resilience.errors import RetryExhaustedError
from app.resilience.fallbacks import degraded_message
from app.resilience.retry import run_with_retry
from app.resilience.timeout import run_with_timeout


def make_retrieve_node(
    retriever: KnowledgeRetriever,
    generator: GroundedAnswerGenerator,
    resilience_config: ResilienceConfig | None = None,
) -> Callable[[AgentState], AgentState]:
    def retrieve_knowledge(state: AgentState) -> AgentState:
        query = state.get("knowledge_query") or _latest_user_message(state)
        timeout_seconds = (resilience_config or ResilienceConfig()).retrieval_timeout_seconds
        try:
            chunks = run_with_retry(
                lambda: run_with_timeout(
                    lambda: retriever.retrieve(query), timeout_seconds=timeout_seconds
                ),
                dependency="retrieval",
                config=resilience_config,
            )
        except RetryExhaustedError as error:
            knowledge_only = state.get("tool_result") is None
            fallback = degraded_message(error.category, knowledge_only=knowledge_only)
            if knowledge_only:
                return {
                    "last_error": fallback,
                    "error_category": AgentErrorCategory.RETRIEVAL_ERROR,
                    "failure_category": error.category.value,
                    "recovery_action": "degraded",
                    "degraded_components": ["retrieval"],
                }
            tool_result = state.get("tool_result") or {}
            current_status = tool_result.get("status")
            business_result = (
                f"The current business result is {current_status}. "
                if current_status is not None
                else "The current business result was retrieved. "
            )
            return {
                "knowledge_answer": business_result + fallback,
                "failure_category": error.category.value,
                "recovery_action": "degraded",
                "degraded_components": ["retrieval"],
            }
        grounded = generator.answer(query, chunks, state.get("tool_result"))
        degraded = getattr(retriever, "last_degraded_components", [])
        return {
            "retrieved_chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "knowledge_answer": grounded.answer,
            "citations": [citation.model_dump(mode="json") for citation in grounded.citations],
            "degraded_components": list(degraded),
            "recovery_action": "degraded" if degraded else None,
        }

    return retrieve_knowledge


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
