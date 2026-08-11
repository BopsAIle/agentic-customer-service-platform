from collections.abc import Callable
from uuid import uuid4

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.policies.confirmation import Clock
from app.policies.engine import PolicyEngine
from app.policies.models import PolicyAuditEvent, PolicyOutcome
from app.policies.registry import InMemoryPolicyAuditLog


def make_evaluate_policy_node(
    engine: PolicyEngine, audit_log: InMemoryPolicyAuditLog, clock: Clock
) -> Callable[[AgentState], AgentState]:
    def evaluate_policy(state: AgentState) -> AgentState:
        tool_name = state.get("selected_tool")
        if not tool_name:
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Policy evaluation requires a selected tool.",
            }
        decision = engine.evaluate(
            tool_name=tool_name,
            customer_id=state.get("customer_id"),
            arguments=state.get("tool_arguments", {}),
        )
        action_id = state.get("action_id") or f"act_{uuid4().hex}"
        audit_log.append(
            PolicyAuditEvent(
                agent_run_id=state["agent_run_id"],
                conversation_id=state["conversation_id"],
                action_id=action_id,
                tool_name=tool_name,
                risk_level=decision.risk_level,
                policy_outcome=decision.outcome,
                reason_codes=decision.reasons,
                timestamp=clock.now(),
            )
        )
        result: AgentState = {"policy_decision": decision, "action_id": action_id}
        if decision.outcome == PolicyOutcome.DENY:
            result.update(
                {
                    "error_category": AgentErrorCategory.POLICY_DENIED,
                    "last_error": "Policy denied the selected action.",
                }
            )
        return result

    return evaluate_policy
