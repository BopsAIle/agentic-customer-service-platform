from collections.abc import Callable

from app.agent.state import AgentState
from app.rag.generation.grounded import GroundedAnswerGenerator
from app.rag.retrieval.service import KnowledgeRetriever


def make_retrieve_node(
    retriever: KnowledgeRetriever,
    generator: GroundedAnswerGenerator,
) -> Callable[[AgentState], AgentState]:
    def retrieve_knowledge(state: AgentState) -> AgentState:
        query = state.get("knowledge_query") or _latest_user_message(state)
        chunks = retriever.retrieve(query)
        grounded = generator.answer(query, chunks, state.get("tool_result"))
        return {
            "retrieved_chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "knowledge_answer": grounded.answer,
            "citations": [citation.model_dump(mode="json") for citation in grounded.citations],
        }

    return retrieve_knowledge


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
