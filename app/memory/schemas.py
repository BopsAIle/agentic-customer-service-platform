from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    SUPPORT_CONTEXT = "support_context"
    EXPLICIT_INSTRUCTION = "explicit_instruction"
    UNRESOLVED_ISSUE = "unresolved_issue"
    INTERACTION_SUMMARY = "interaction_summary"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemorySource(StrEnum):
    USER_EXPLICIT = "user_explicit"
    AGENT_INFERRED = "agent_inferred"


class MemorySensitivityLevel(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class MemoryRetentionPolicy(StrEnum):
    STANDARD = "standard"
    SHORT = "short"
    NO_STORE = "no_store"


class MemoryStorageEligibility(StrEnum):
    ALLOWED = "allowed"
    REDACT = "redact"
    REJECT = "reject"


class MemoryRedactionState(StrEnum):
    NOT_REQUIRED = "not_required"
    REDACTED = "redacted"
    REJECTED = "rejected"


class MemoryCandidate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=300)
    normalized_key: str = Field(min_length=2, max_length=64)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    explicit_user_request: bool = False


class MemoryRecordView(BaseModel):
    id: int
    customer_id: int
    memory_type: MemoryType
    content: str
    normalized_key: str
    source: MemorySource
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    status: MemoryStatus
    sensitivity_level: MemorySensitivityLevel = MemorySensitivityLevel.INTERNAL
    retention_policy: MemoryRetentionPolicy = MemoryRetentionPolicy.STANDARD
    redaction_state: MemoryRedactionState = MemoryRedactionState.NOT_REQUIRED


class MemoryPolicyDecision(BaseModel):
    outcome: str
    candidate: MemoryCandidate | None = None
    reason: str
    sensitivity_level: MemorySensitivityLevel = MemorySensitivityLevel.INTERNAL
    retention_policy: MemoryRetentionPolicy = MemoryRetentionPolicy.STANDARD
    storage_eligibility: MemoryStorageEligibility = MemoryStorageEligibility.ALLOWED
    redaction_state: MemoryRedactionState = MemoryRedactionState.NOT_REQUIRED
    security_signal: str | None = None


class MemoryOperationResult(BaseModel):
    status: str
    record: MemoryRecordView | None = None
    affected_count: int = 0
    reason: str | None = None
    security_signal: str | None = None
