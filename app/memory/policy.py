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

# Authority claim patterns là các patterns để phát hiện authority claim
_AUTHORITY_CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:i am|i'm|i am now|you are|you're)\s+(?:the\s+)?"
        r"(?:(?:an?\s+)?(?:system|account|support)\s+)?(?:an?\s+)?"
        r"(?:admin|administrator|manager|owner|superuser|support operator)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i have|give me|grant me)\s+(?:admin|administrator|manager|owner|"
        r"superuser|support operator)?\s*(?:permissions?|privileges?|authority|access)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|the)\s+manager\s+(?:has\s+)?(?:approved|authorized|allows?|permitted)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i|we|my\s+account)\b.*\b(?:have|has|got|received)\b.*"
        r"\b(?:admin|administrator|manager|operator|support)?\s*"
        r"(?:approval|authorization|permissions?|privileges?|authority)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:approved|authorized|permission|permitted)\b.*"
        r"\b(?:all\s+)?(?:refunds?|cancellations?|actions?|orders?)\b.*"
        r"\b(?:for|on)\s+(?:my|this)\s+account\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:support|manager|company)\b\s+(?:already\s+)?"
        r"(?:approved|authorized|permitted)\b.*\b(?:all|future|any|unlimited)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:admin|administrator|manager|yetki|yönetici)\b.*"
        r"\b(?:onay|izin|refund|iade|cancel|iptal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:automatic|auto|always)\s+(?:approval|approved|authorization|"
        r"authorized|permission|permitted)\b.*"
        r"\b(?:refunds?|cancellations?|actions?|orders?|iade|iptal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:approval|authorization|permission|approval rights)\b.*"
        r"\b(?:for|on)\s+(?:my|this)\s+account\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:refund|iade|cancellation|cancel|iptal)\b.*"
        r"\b(?:approval|authorization|permission|privileges?|authority|access)\b|"
        r"\b(?:approval|authorization|permission|privileges?|authority|access)\b.*"
        r"\b(?:refund|iade|cancellation|cancel|iptal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:user|customer|account holder)\b.*"
        r"\b(?:admin|administrator|manager|owner|superuser|support operator|"
        r"approval|authorization|permission|privileges?|authority)\b",
        re.IGNORECASE,
    ),
)
# Authority override patterns là các patterns để phát hiện authority override
_AUTHORITY_OVERRIDE_PATTERNS = (
    re.compile(
        r"\b(?:skip|bypass|avoid|without)\s+(?:the\s+)?"
        r"(?:confirmation|approval|verification|validation|checks?|safeguards?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:don't|do not|never|no longer)\s+(?:need|needs?|require|requires?)\s+"
        r"(?:the\s+)?(?:confirmation|approval|verification|validation|checks?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|this|the)\s+(?:account|profile)\b.*\b(?:don't|do not|doesn't|"
        r"does not|no longer)\s+(?:need|needs?|require|requires?)\s+"
        r"(?:the\s+)?(?:confirmation|approval|verification|validation|checks?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:no|without)\s+(?:the\s+)?(?:confirmation|approval|verification|"
        r"validation|checks?)\s+(?:is\s+)?(?:required|needed)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:future|all|any|every)\s+(?:refunds?|cancellations?|actions?)\b.*"
        r"\b(?:skip|bypass|without|no|automatic|auto|pre[- ]?approved|always\s+approved)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|this|the)\s+account\b.*\b(?:automatic|auto|unlimited)\s+"
        r"(?:approval|authorization)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:already|permanently)\s+authorized\b|"
        r"\bpre[- ]?approved\b|\bpermanent(?:ly)?\s+authorization\b|"
        r"\b(?:trusted|approved)\s+account\b.*\b(?:without|no)\s+"
        r"(?:verification|validation|checks?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:bypass|skip|override|disable|ignore)\b.*"
        r"\b(?:policy|validation|verification|confirmation|approval|checks?|safeguards?)\b",
        re.IGNORECASE,
    ),
)
_MEMORY_REQUEST_MARKER = re.compile(
    r"\b(?:remember|save|store|keep)\b|"
    r"\b(?:update|add)\b.*\b(?:memory|preference)\b",
    re.IGNORECASE,
)

## hàm này chặn prompt injection kiểu “nhớ giúp tôi là admin / khỏi cần confirm” trước khi hệ thống tin memory hay tin model
# Nếu có các từ xuất hiện trong 2 tập _AUTHORITY_OVERRIDE_PATTERNS hoặc _AUTHORITY_CLAIM_PATTERNS thì trả về "memory_security_override_attempt"
def classify_memory_security_message(message: str) -> str | None:
    """Classify raw memory requests before any memory lookup or mutation.

    This intentionally operates on the user's bounded message, not on a model
    generated candidate.  A model must not be able to paraphrase an authority
    claim into an apparently harmless preference before the memory boundary.
    """

    normalized = " ".join(message.split())
    if not normalized or not _MEMORY_REQUEST_MARKER.search(normalized):
        return None
    if any(pattern.search(normalized) for pattern in _AUTHORITY_OVERRIDE_PATTERNS):
        return "memory_security_override_attempt"
    if any(pattern.search(normalized) for pattern in _AUTHORITY_CLAIM_PATTERNS):
        return "memory_security_override_attempt"
    return None


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
    if any(pattern.search(candidate_value.content) for pattern in _AUTHORITY_OVERRIDE_PATTERNS):
        return MemoryPolicyDecision(
            outcome="reject",
            candidate=candidate_value,
            reason="security_override_not_storable",
            security_signal="memory_security_override_attempt",
            **metadata,
        )
    if any(pattern.search(candidate_value.content) for pattern in _AUTHORITY_CLAIM_PATTERNS):
        return MemoryPolicyDecision(
            outcome="reject",
            candidate=candidate_value,
            reason="authority_claim_not_storable",
            security_signal="memory_authority_claim_rejected",
            **metadata,
        )
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
