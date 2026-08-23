from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.nodes.execute_tool import make_execute_tool_node
from app.agent.state import AgentState
from app.policies.confirmation import Clock
from app.policies.models import PendingActionStatus
from app.policies.repository import PolicyAuditRepository
from app.resilience.config import ResilienceConfig
from app.resilience.control import ReliabilityController


def make_confirmed_execution_node(
    session: Session,
    resilience_config: ResilienceConfig | None = None,
    audit_repository: PolicyAuditRepository | None = None,
    clock: Clock | None = None,
    reliability_controller: ReliabilityController | None = None,
) -> Callable[[AgentState], AgentState]:
    execute = make_execute_tool_node(
        session,
        resilience_config,
        audit_repository,
        clock,
        reliability_controller,
    )

    def execute_confirmed(state: AgentState) -> AgentState:
        result = execute(state)
        action = state.get("pending_action")
        if action is None:
            return result
        final_status = (
            PendingActionStatus.EXECUTED
            if result.get("tool_execution_status") == "executed"
            else PendingActionStatus.FAILED
        )
        result["pending_action"] = action.model_copy(update={"status": final_status})
        return result

    return execute_confirmed
