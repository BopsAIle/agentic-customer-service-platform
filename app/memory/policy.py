from __future__ import annotations

import re

from app.memory.dlp import classify_candidate, detected_types
from app.memory.schemas import (
    MemoryCandidate,
    MemoryPolicyDecision,
    MemoryStorageEligibility,
    MemoryType,
)

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
    classified = classify_candidate(normalized)
    candidate_value = classified.candidate
    metadata = {
        "sensitivity_level": classified.sensitivity_level,
        "retention_policy": classified.retention_policy,
        "storage_eligibility": classified.storage_eligibility,
        "redaction_state": classified.redaction_state,
    }
    if classified.storage_eligibility == MemoryStorageEligibility.REJECT:
        types = ",".join(data_type.value for data_type in detected_types(normalized))
        return MemoryPolicyDecision(
            outcome="reject",
            candidate=candidate_value,
            reason=f"dlp_restricted_content:{types or 'sensitive_data'}",
            **metadata,
        )
    if not _KEY_PATTERN.fullmatch(candidate_value.normalized_key):
        return MemoryPolicyDecision(
            outcome="reject", reason="invalid_memory_key", candidate=candidate_value, **metadata
        )
    if len(candidate_value.content) > 300:
        return MemoryPolicyDecision(
            outcome="reject",
            reason="memory_content_too_long",
            candidate=candidate_value,
            **metadata,
        )
    lowered = candidate_value.content.casefold()
    if any(pattern in lowered for pattern in _REJECTED_PATTERNS):
        return MemoryPolicyDecision(
            outcome="reject",
            reason="sensitive_or_instructional_content",
            candidate=candidate_value,
            **metadata,
        )
    if (
        candidate_value.memory_type == MemoryType.PREFERENCE
        and candidate_value.normalized_key in _AUTO_PREFERENCE_KEYS
    ):
        return MemoryPolicyDecision(
            outcome="allow", candidate=candidate_value, reason="low_risk_preference", **metadata
        )
    if candidate_value.explicit_user_request:
        return MemoryPolicyDecision(
            outcome="allow", candidate=candidate_value, reason="explicit_user_request", **metadata
        )
    return MemoryPolicyDecision(
        outcome="require_explicit",
        candidate=candidate_value,
        reason="durable_context_requires_consent",
        **metadata,
    )
