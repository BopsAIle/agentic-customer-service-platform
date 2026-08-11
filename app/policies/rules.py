from app.policies.models import PolicyDecision, PolicyOutcome
from app.tools import registry


def evaluate_default_policy(
    tool_name: str,
    customer_id: int | None,
    arguments: dict[str, object],
) -> PolicyDecision:
    metadata = registry.TOOL_REGISTRY.get(tool_name)
    if metadata is None:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            tool_name=tool_name,
            risk_level=-1,
            reasons=["unknown_tool"],
            required_conditions=[],
        )
    if customer_id is None or customer_id <= 0:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            tool_name=tool_name,
            risk_level=int(metadata.risk_level),
            reasons=["known_customer_required"],
            required_conditions=["authenticated_customer"],
        )
    requested_customer = arguments.get("customer_id")
    if requested_customer is not None and requested_customer != customer_id:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            tool_name=tool_name,
            risk_level=int(metadata.risk_level),
            reasons=["ownership_required"],
            required_conditions=["customer_ownership"],
        )
    risk_level = int(metadata.risk_level)
    if risk_level <= 1:
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            tool_name=tool_name,
            risk_level=risk_level,
            reasons=["risk_policy_allows_automatic_execution"],
            required_conditions=[],
        )
    if risk_level == 2:
        return PolicyDecision(
            outcome=PolicyOutcome.REQUIRE_CONFIRMATION,
            tool_name=tool_name,
            risk_level=risk_level,
            reasons=["customer_impacting_write"],
            required_conditions=["explicit_confirmation", "pre_execution_revalidation"],
        )
    return PolicyDecision(
        outcome=PolicyOutcome.REQUIRE_HUMAN,
        tool_name=tool_name,
        risk_level=risk_level,
        reasons=["human_controlled_action"],
        required_conditions=["dedicated_human_path"],
    )
