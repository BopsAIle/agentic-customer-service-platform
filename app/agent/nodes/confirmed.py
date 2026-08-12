from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.nodes.execute_tool import make_execute_tool_node
from app.agent.state import AgentState
from app.policies.confirmation import Clock
from app.policies.models import PendingActionStatus, PolicyAuditEvent, PolicyOutcome
from app.policies.repository import PolicyAuditRepository
from app.resilience.config import ResilienceConfig


def make_confirmed_execution_node(
    session: Session,
    resilience_config: ResilienceConfig | None = None,
    audit_repository: PolicyAuditRepository | None = None,
    clock: Clock | None = None,
) -> Callable[[AgentState], AgentState]:
    execute = make_execute_tool_node(session, resilience_config)

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
        if audit_repository is not None and clock is not None:
            context = state.get("execution_context")
            if context is not None:
                audit_repository.append(
                    PolicyAuditEvent(
                        agent_run_id=state["agent_run_id"],
                        request_id=context.request_id,
                        conversation_id=context.conversation_id,
                        actor_id=context.principal.actor_id,
                        actor_type=context.principal.actor_type,
                        roles=list(context.principal.roles),
                        effective_customer_id=context.effective_customer_id,
                        action_id=action.action_id,
                        tool_name=action.tool_name,
                        risk_level=action.risk_level,
                        policy_outcome=(
                            PolicyOutcome.ALLOW
                            if final_status == PendingActionStatus.EXECUTED
                            else PolicyOutcome.DENY
                        ),
                        reason_codes=[
                            "execution_succeeded"
                            if final_status == PendingActionStatus.EXECUTED
                            else "execution_failed"
                        ],
                        timestamp=clock.now(),
                        stage="execution",
                        confirmation_status="confirmed",
                        revalidation=True,
                        execution_status=final_status.value,
                    )
                )
        return result

    return execute_confirmed
