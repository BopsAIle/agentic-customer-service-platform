from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.memory.service import MemoryService
from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.resilience.config import ResilienceConfig
from app.resilience.control import ReliabilityController
from app.resilience.errors import ResilienceError, RetryExhaustedError
from app.resilience.retry import run_with_retry

##Đọc memory của khách theo execution_context.
#  Fail thì không chặn request — tiếp tục với memory_context rỗng (continue_without_memory).
def make_retrieve_memory_node(
    service: MemoryService,
    session: Session,
    resilience_config: ResilienceConfig | None = None,
    reliability_controller: ReliabilityController | None = None,
) -> Callable[[AgentState], AgentState]:
    def retrieve_memory(state: AgentState) -> AgentState:
        context = state.get("execution_context")
        if context is None:
            return {
                "memory_context": [],
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Authenticated execution context is required for memory.",
            }
        query = _latest_user_message(state)
        with span("memory.retrieve") as memory_span:
            try:
                records = run_with_retry(
                    lambda: service.retrieve(
                        session,
                        context.effective_customer_id,
                        query,
                        principal=context.principal,
                    ),
                    dependency="memory",
                    config=resilience_config,
                    controller=reliability_controller,
                    service_identity="memory:postgres",
                )
            except (RetryExhaustedError, ResilienceError) as error:
                memory_span.set_attribute("memory.status", "degraded")
                get_metrics().memory_reads_total.add(1, {"status": "degraded"})
                return {
                    "memory_context": [],
                    "failure_category": error.category.value,
                    "degraded_components": ["memory"],
                    "recovery_action": "continue_without_memory",
                }
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
