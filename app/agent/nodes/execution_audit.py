from __future__ import annotations

from app.agent.state import AgentState
from app.policies.confirmation import Clock
from app.policies.models import PolicyAuditEvent, PolicyOutcome, stable_policy_event_id
from app.policies.repository import PolicyAuditRepository, append_policy_audit


def record_execution_event(
    state: AgentState,
    audit_repository: PolicyAuditRepository,
    clock: Clock,
    *,
    status: str,
    failure_category: str | None = None,
) -> None:
    """Persist safe, idempotent evidence for an agent-originated business write."""

    context = state.get("execution_context")
    tool_name = state.get("selected_tool")
    if context is None or not tool_name:
        return

    metadata = state.get("policy_decision")
    pending_action = state.get("pending_action")
    action_id = state.get("action_id") or (
        pending_action.action_id if pending_action is not None else None
    )
    risk_level = (
        metadata.risk_level
        if metadata is not None
        else (pending_action.risk_level if pending_action is not None else 0)
    )
    policy_outcome = (
        metadata.outcome
        if metadata is not None
        else (
            PolicyOutcome.ALLOW
            if pending_action is not None
            else PolicyOutcome.REQUIRE_HUMAN
            if tool_name == "escalate_to_human"
            else PolicyOutcome.ALLOW
        )
    )
    confirmed = pending_action is not None
    event_id = stable_policy_event_id(state["agent_run_id"], action_id, "execution", status)
    reason = {
        "attempted": "execution_attempted",
        "success": "execution_succeeded",
        "failure": "execution_failed",
        "unknown": "execution_unknown",
    }[status]
    reason_codes = [reason]
    if failure_category is not None:
        reason_codes.append(failure_category)
    append_policy_audit(
        audit_repository,
        PolicyAuditEvent(
            event_id=event_id,
            agent_run_id=state["agent_run_id"],
            request_id=context.request_id,
            conversation_id=context.conversation_id,
            actor_id=context.principal.actor_id,
            actor_type=context.principal.actor_type,
            roles=list(context.principal.roles),
            effective_customer_id=context.effective_customer_id,
            action_id=action_id,
            tool_name=tool_name,
            risk_level=risk_level,
            policy_outcome=policy_outcome,
            reason_codes=reason_codes,
            timestamp=clock.now(),
            stage="execution",
            confirmation_status="confirmed" if confirmed else None,
            revalidation=confirmed,
            execution_status=status,
        ),
    )
