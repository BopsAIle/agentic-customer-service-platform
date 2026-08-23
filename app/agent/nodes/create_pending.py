from collections.abc import Callable
from uuid import uuid4

from app.agent.state import AgentState
from app.policies.confirmation import Clock
from app.policies.models import PendingAction, PolicyOutcome


def make_create_pending_node(clock: Clock) -> Callable[[AgentState], AgentState]:
    def create_pending(state: AgentState) -> AgentState:
        decision = state["policy_decision"]
        tool_name = state["selected_tool"]
        if (
            decision is None
            or tool_name is None
            or decision.outcome != PolicyOutcome.REQUIRE_CONFIRMATION
        ):
            return {}
        action_id = state.get("action_id") or f"act_{uuid4().hex}"
        context = state["execution_context"]
        action = PendingAction(
            action_id=action_id,
            conversation_id=context.conversation_id,
            tenant_id=context.tenant_id,
            actor_id=context.principal.actor_id,
            actor_type=context.principal.actor_type,
            effective_customer_id=context.effective_customer_id,
            tool_name=tool_name,
            arguments=state.get("tool_arguments", {}),
            risk_level=decision.risk_level,
            created_at=clock.now(),
        )
        return {
            "pending_action": action,
            "action_id": action_id,
            "tool_execution_status": "pending",
        }

    return create_pending
