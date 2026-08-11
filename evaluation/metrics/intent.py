from collections.abc import Sequence

from app.agent.schemas import AgentRequestType, Intent


def accuracy(actual: Sequence[Intent], expected: Intent | None) -> bool | None:
    if expected is None:
        return None
    return bool(actual) and actual[0] == expected


def request_type_accuracy(
    actual: Sequence[AgentRequestType], expected: AgentRequestType | None
) -> bool | None:
    if expected is None:
        return None
    return bool(actual) and actual[0] == expected
