"""Canonical operator trace stage mapping."""

from app.ui.schemas import UITraceStage

_NODE_TO_STAGE: dict[str, UITraceStage] = {
    "load_context": UITraceStage.USER_REQUEST,
    "understand_request": UITraceStage.INTENT_DETECTION,
    "retrieve_memory": UITraceStage.MEMORY_CONTEXT,
    "retrieve_knowledge": UITraceStage.CONTEXT_RETRIEVAL,
    "compile_decision": UITraceStage.GROUNDING,
    "validate_tool": UITraceStage.TARGET_VALIDATION,
    "evaluate_policy": UITraceStage.POLICY_EVALUATION,
    "policy_revalidate": UITraceStage.POLICY_EVALUATION,
    "inspect_risk": UITraceStage.POLICY_EVALUATION,
    "check_pending_action": UITraceStage.CONFIRMATION,
    "create_pending_action": UITraceStage.CONFIRMATION,
    "execute_tool": UITraceStage.EXECUTION_AUTHORITY,
    "escalate": UITraceStage.EXECUTION_AUTHORITY,
    "memory_action": UITraceStage.MEMORY_CONTEXT,
    "route_request": UITraceStage.ROUTING,
    "respond": UITraceStage.RESPONSE,
}

_NODE_TO_EVENT: dict[str, str] = {
    "load_context": "request.received",
    "retrieve_memory": "context.loaded",
    "retrieve_knowledge": "context.loaded",
    "understand_request": "proposal.generated",
    "compile_decision": "proposal.validated",
    "validate_tool": "decision.compiled",
    "evaluate_policy": "policy.checked",
    "policy_revalidate": "policy.checked",
    "check_pending_action": "confirmation.resolved",
    "create_pending_action": "confirmation.required",
    "execute_tool": "authority.executed",
    "escalate": "authority.executed",
    "respond": "evidence.persisted",
}


def trace_stage_for_node(name: str) -> UITraceStage:
    """Return the stable stage ID for an internal runtime node name."""

    return _NODE_TO_STAGE.get(name, UITraceStage.INTERNAL)


def trace_event_key_for_node(name: str) -> str | None:
    return _NODE_TO_EVENT.get(name)
