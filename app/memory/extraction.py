from __future__ import annotations

import re

from app.memory.schemas import MemoryCandidate, MemoryType


def extract_memory_request(message: str) -> tuple[MemoryCandidate | None, str | None]:
    normalized = " ".join(message.casefold().split())
    if "forget" in normalized or "don't remember" in normalized or "do not remember" in normalized:
        if "email" in normalized:
            return None, "contact_channel"
        if "concise" in normalized or "short" in normalized:
            return None, "response_style"
        return None, None
    if not (normalized.startswith("remember") or "remember that" in normalized):
        return None, None
    if "email" in normalized:
        return (
            MemoryCandidate(
                memory_type=MemoryType.PREFERENCE,
                content="The customer prefers email updates.",
                normalized_key="contact_channel",
                explicit_user_request=True,
            ),
            None,
        )
    if "sms" in normalized or "text message" in normalized:
        return (
            MemoryCandidate(
                memory_type=MemoryType.PREFERENCE,
                content="The customer prefers SMS updates.",
                normalized_key="contact_channel",
                explicit_user_request=True,
            ),
            None,
        )
    if "concise" in normalized or "short" in normalized:
        return (
            MemoryCandidate(
                memory_type=MemoryType.PREFERENCE,
                content="The customer prefers concise answers.",
                normalized_key="response_style",
                explicit_user_request=True,
            ),
            None,
        )
    match = re.search(r"remember(?: that)? (.+)", normalized)
    if match:
        return (
            MemoryCandidate(
                memory_type=MemoryType.SUPPORT_CONTEXT,
                content=match.group(1),
                normalized_key="support_context",
                explicit_user_request=True,
            ),
            None,
        )
    return None, None
