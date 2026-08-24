import hashlib
import json
from typing import Any

from app.agent.schemas import AgentRequestType, Intent, SemanticDecision, SemanticTarget
from app.core.context import ExecutionContext
from app.policies.models import PendingAction

POLICY_INPUTS_SCHEMA_VERSION = 1

_TOOL_INTENTS = {
    "cancel_order": Intent.ORDER_CANCEL,
    "request_refund": Intent.REFUND_REQUEST,
    "create_support_ticket": Intent.TICKET_CREATE,
    "escalate_to_human": Intent.HUMAN_ESCALATION,
}


def restore_pending_arguments(action: PendingAction) -> dict[str, object]:
    """Restore only bounded action arguments captured before confirmation."""

    policy_arguments = action.policy_inputs.get("arguments")
    arguments = (
        dict(policy_arguments) if isinstance(policy_arguments, dict) else dict(action.arguments)
    )
    for key in ("customer_id", "order_id", "ticket_id", "reason", "category", "description"):
        value = action.collected_entities.get(key)
        if value is not None:
            arguments.setdefault(key, value)
    return arguments


def build_policy_inputs(
    *,
    context: ExecutionContext,
    tool_name: str,
    arguments: dict[str, object],
    outcome: str,
    risk_level: int,
    reasons: list[str],
    required_conditions: list[str],
) -> dict[str, Any]:
    """Capture bounded inputs used by the policy engine at the gate."""

    return {
        "schema_version": POLICY_INPUTS_SCHEMA_VERSION,
        "tool_name": tool_name,
        "arguments": _json_value(arguments),
        "context": build_policy_context(context),
        "outcome": outcome,
        "risk_level": risk_level,
        "reasons": list(reasons),
        "required_conditions": list(required_conditions),
    }


def restore_policy_inputs(
    action: PendingAction,
    context: ExecutionContext,
    arguments: dict[str, object],
) -> dict[str, Any]:
    """Restore the persisted policy snapshot with normalized current inputs.

    The persisted snapshot is observational. Current authenticated context remains
    the authority used by the policy engine during revalidation.
    """

    restored = dict(action.policy_inputs)
    restored["schema_version"] = restored.get("schema_version", POLICY_INPUTS_SCHEMA_VERSION)
    restored["tool_name"] = action.tool_name
    restored["arguments"] = _json_value(arguments)
    restored["context"] = build_policy_context(context)
    return restored


def build_policy_context(context: ExecutionContext) -> dict[str, Any]:
    """Return policy-relevant identity/scope, excluding per-request transport IDs."""

    return {
        "conversation_id": context.conversation_id,
        "tenant_id": context.tenant_id,
        "effective_customer_id": context.effective_customer_id,
        "actor_id": context.principal.actor_id,
        "actor_type": context.principal.actor_type.value,
        "principal_type": context.principal.principal_type.value,
        "roles": sorted(context.principal.roles),
        "groups": sorted(context.principal.groups),
    }


def hash_policy_inputs(policy_inputs: dict[str, Any]) -> str:
    canonical = normalize_policy_inputs(policy_inputs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_policy_inputs(policy_inputs: dict[str, Any]) -> str:
    """Serialize the bounded snapshot without adding hidden runtime data."""

    return json.dumps(
        _json_value(policy_inputs),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_policy_inputs(policy_inputs: dict[str, Any]) -> str:
    """Return the canonical representation used for equality and hashing."""

    return json.dumps(
        _json_value(policy_inputs),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def policy_input_diff(original: dict[str, Any], restored: dict[str, Any]) -> dict[str, list[str]]:
    """Return bounded field paths without exposing policy input values."""

    original_flat = _flatten(original)
    restored_flat = _flatten(restored)
    return {
        "missing": sorted(set(original_flat) - set(restored_flat)),
        "added": sorted(set(restored_flat) - set(original_flat)),
        "changed": sorted(
            key
            for key in set(original_flat).intersection(restored_flat)
            if original_flat[key] != restored_flat[key]
        ),
    }


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        flattened: dict[str, str] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(item, path))
        return flattened
    if isinstance(value, list):
        return {prefix: json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))}
    return {prefix: json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))}


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def restore_pending_decision(
    action: PendingAction, arguments: dict[str, object]
) -> SemanticDecision | None:
    if action.intent is None:
        return None
    try:
        intent = Intent(action.intent)
    except ValueError:
        return None
    # Legacy direct-tool providers could report a generic semantic intent while
    # selecting a concrete tool. The persisted tool remains the bounded source
    # for compiler resumption; this does not grant authority or skip validation.
    tool_intent = _TOOL_INTENTS.get(action.tool_name)
    if tool_intent is not None and tool_intent != intent:
        intent = tool_intent
    target: SemanticTarget | None = None
    order_id = arguments.get("order_id")
    ticket_id = arguments.get("ticket_id")
    if isinstance(order_id, int) and order_id > 0:
        target = SemanticTarget(type="explicit_order", order_id=order_id)
    elif isinstance(ticket_id, int) and ticket_id > 0:
        target = SemanticTarget(type="explicit_ticket", ticket_id=ticket_id)
    return SemanticDecision(
        intent=intent,
        request_type=AgentRequestType.WRITE_ACTION,
        target=target,
        reason=str(arguments.get("reason", "")),
        category=_optional_text(arguments.get("category")),
        description=_optional_text(arguments.get("description")),
        priority=_optional_text(arguments.get("priority")),
        summary=_optional_text(arguments.get("summary")),
    )


def restored_field_count(action: PendingAction, arguments: dict[str, object]) -> int:
    fields = {
        "intent": action.intent,
        "tool_name": action.tool_name,
        "tool_arguments": arguments,
        "collected_entities": action.collected_entities,
        "policy_inputs": action.policy_inputs,
        "validation_context": action.validation_context,
    }
    return sum(bool(value) for value in fields.values())


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
