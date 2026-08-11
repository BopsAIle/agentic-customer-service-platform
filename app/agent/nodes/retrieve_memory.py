from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.state import AgentState
from app.memory.service import MemoryService
from app.observability.metrics import get_metrics
from app.observability.tracing import span


def make_retrieve_memory_node(
    service: MemoryService, session: Session
) -> Callable[[AgentState], AgentState]:
    def retrieve_memory(state: AgentState) -> AgentState:
        query = _latest_user_message(state)
        with span("memory.retrieve") as memory_span:
            records = service.retrieve(session, state["customer_id"], query)
            memory_span.set_attribute("memory.result_count", len(records))
            memory_span.set_attribute(
                "memory.types",
                sorted(
                    {getattr(record.memory_type, "value", record.memory_type) for record in records}
                )[:10],
            )
            get_metrics().memory_reads_total.add(1, {"status": "ok"})
        return {"memory_context": [record.model_dump(mode="json") for record in records]}

    return retrieve_memory


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
