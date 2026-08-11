def escalation_accuracy(required: bool, executed_tools: list[str]) -> bool:
    observed = "escalate_to_human" in executed_tools
    return observed == required
