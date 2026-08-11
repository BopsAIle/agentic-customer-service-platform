from __future__ import annotations

import re

from app.memory.schemas import MemoryCandidate, MemoryPolicyDecision, MemoryType

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_REJECTED_PATTERNS = (
    "password",
    "credit card",
    "card number",
    "api key",
    "access token",
    "secret",
    "ssn",
    "medical",
    "ignore policy",
    "cancel every order",
    "refund every order",
)
_AUTO_PREFERENCE_KEYS = {
    "response_style",
    "contact_channel",
    "language",
    "support_channel",
}


def normalize_candidate(candidate: MemoryCandidate) -> MemoryCandidate:
    content = " ".join(candidate.content.split())
    key = candidate.normalized_key.casefold().replace("-", "_").replace(" ", "_")
    return candidate.model_copy(update={"content": content, "normalized_key": key})


def evaluate_candidate(candidate: MemoryCandidate) -> MemoryPolicyDecision:
    normalized = normalize_candidate(candidate)
    lowered = normalized.content.casefold()
    if not _KEY_PATTERN.fullmatch(normalized.normalized_key):
        return MemoryPolicyDecision(outcome="reject", reason="invalid_memory_key")
    if len(normalized.content) > 300:
        return MemoryPolicyDecision(outcome="reject", reason="memory_content_too_long")
    if any(pattern in lowered for pattern in _REJECTED_PATTERNS):
        return MemoryPolicyDecision(outcome="reject", reason="sensitive_or_instructional_content")
    if (
        normalized.memory_type == MemoryType.PREFERENCE
        and normalized.normalized_key in _AUTO_PREFERENCE_KEYS
    ):
        return MemoryPolicyDecision(
            outcome="allow", candidate=normalized, reason="low_risk_preference"
        )
    if normalized.explicit_user_request:
        return MemoryPolicyDecision(
            outcome="allow", candidate=normalized, reason="explicit_user_request"
        )
    return MemoryPolicyDecision(
        outcome="require_explicit",
        candidate=normalized,
        reason="durable_context_requires_consent",
    )
