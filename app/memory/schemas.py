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


class MemoryPolicyDecision(BaseModel):
    outcome: str
    candidate: MemoryCandidate | None = None
    reason: str


class MemoryOperationResult(BaseModel):
    status: str
    record: MemoryRecordView | None = None
    affected_count: int = 0
    reason: str | None = None
