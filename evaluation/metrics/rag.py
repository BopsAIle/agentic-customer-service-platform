from collections.abc import Sequence
from typing import Any


def citation_integrity(
    citations: Sequence[dict[str, Any]], retrieved: Sequence[dict[str, Any]]
) -> bool:
    valid = {
        str(item.get("citation_id") or f"{item.get('document_id')}#{item.get('section')}")
        for item in retrieved
    }
    return all(item.get("citation_id") in valid and item.get("source") for item in citations)
