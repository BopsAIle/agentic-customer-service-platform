from app.policies.models import PolicyDecision
from app.policies.rules import evaluate_default_policy


class PolicyEngine:
    def evaluate(
        self,
        *,
        tool_name: str,
        customer_id: int | None,
        arguments: dict[str, object],
    ) -> PolicyDecision:
        return evaluate_default_policy(tool_name, customer_id, arguments)
