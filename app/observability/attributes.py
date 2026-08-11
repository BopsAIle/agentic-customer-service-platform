from collections.abc import Mapping
from typing import Any

from opentelemetry.trace import Span


def set_safe_attributes(span: Span, attributes: Mapping[str, Any]) -> None:
    """Set only explicitly prepared, low-cardinality observability attributes."""

    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)
        elif isinstance(value, (list, tuple)):
            bounded = [str(item) for item in value if isinstance(item, (str, int, float, bool))]
            span.set_attribute(key, bounded[:20])


def error_attributes(category: object | None) -> dict[str, str]:
    if category is None:
        return {}
    value = getattr(category, "value", category)
    return {"error.category": str(value)}
