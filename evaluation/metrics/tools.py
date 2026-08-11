from collections.abc import Sequence
from typing import Any


def selection_accuracy(
    selected: Sequence[str], expected: Sequence[str], forbidden: Sequence[str]
) -> bool:
    return list(selected) == list(expected) and not set(selected).intersection(forbidden)


def argument_accuracy(actual: Sequence[dict[str, Any]], expected: dict[str, Any]) -> bool | None:
    if not expected:
        return None
    return bool(actual) and all(actual[0].get(key) == value for key, value in expected.items())
