import time
from collections.abc import Callable
from uuid import uuid4

from app.agent.errors import RuntimeFailureSource, classify_runtime_error
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.observability.metrics import get_metrics
from app.observability.tracing import span
from app.policies.confirmation import Clock
from app.policies.engine import PolicyEngine
from app.policies.models import PolicyAuditEvent, PolicyOutcome, stable_policy_event_id
from app.policies.repository import PolicyAuditRepository, append_policy_audit
from app.resilience.errors import FailureCategory


def make_evaluate_policy_node(
    engine: PolicyEngine, audit_repository: PolicyAuditRepository, clock: Clock
) -> Callable[[AgentState], AgentState]:
    def evaluate_policy(state: AgentState) -> AgentState:
        started = time.perf_counter()
        outcome = "not_evaluated"
        tool_name = state.get("selected_tool")
        if not tool_name:
            get_metrics().policy_evaluation_duration_seconds.record(
                time.perf_counter() - started, {"status": outcome}
            )
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Policy evaluation requires a selected tool.",
            }
        context = state.get("execution_context")
        if context is None:
            get_metrics().policy_evaluation_duration_seconds.record(
                time.perf_counter() - started, {"status": outcome}
            )
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Authenticated execution context is required.",
            }
        with span(
            "policy.evaluate",
            attributes={"tool.name": tool_name},
        ) as policy_span:
            try:
                decision = engine.evaluate(
                    tool_name=tool_name,
                    context=context,
                    arguments=state.get("tool_arguments", {}),
                )
            except Exception as error:
                outcome = "fail_closed"
                policy_span.set_attribute("policy.outcome", "fail_closed")
                get_metrics().policy_evaluation_duration_seconds.record(
                    time.perf_counter() - started, {"status": outcome}
                )
                classification = classify_runtime_error(error, source=RuntimeFailureSource.POLICY)
                return {
                    "error_category": classification.category,
                    "failure_category": FailureCategory.POLICY_FAILURE.value,
                    "recovery_action": "deny",
                    "last_error": "Policy evaluation failed closed.",
                }
            policy_span.set_attribute("policy.outcome", decision.outcome.value)
            policy_span.set_attribute("tool.risk_level", decision.risk_level)
            policy_span.set_attribute("policy.reason_codes", decision.reasons[:10])
        outcome = decision.outcome.value
        get_metrics().policy_evaluation_duration_seconds.record(
            time.perf_counter() - started, {"status": outcome}
        )
        get_metrics().policy_decisions_total.add(
            1,
            {"policy_outcome": decision.outcome.value, "risk_level": str(decision.risk_level)},
        )
        action_id = state.get("action_id") or f"act_{uuid4().hex}"
        append_policy_audit(
            audit_repository,
            PolicyAuditEvent(
                event_id=stable_policy_event_id(
                    state["agent_run_id"], action_id, "policy_evaluation", decision.outcome.value
                ),
                agent_run_id=state["agent_run_id"],
                request_id=context.request_id,
                conversation_id=context.conversation_id,
                tenant_id=context.tenant_id,
                actor_id=context.principal.actor_id,
                actor_type=context.principal.actor_type,
                roles=list(context.principal.roles),
                effective_customer_id=context.effective_customer_id,
                action_id=action_id,
                tool_name=tool_name,
                risk_level=decision.risk_level,
                policy_outcome=decision.outcome,
                reason_codes=decision.reasons,
                timestamp=clock.now(),
                stage="policy_evaluation",
                confirmation_status=(
                    "required" if decision.outcome == PolicyOutcome.REQUIRE_CONFIRMATION else None
                ),
            ),
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
