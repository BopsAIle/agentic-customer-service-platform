from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.auth.models import ActorType


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_HUMAN = "require_human"
    DENY = "deny"


class PendingActionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class PendingAction(BaseModel):
    action_id: str
    conversation_id: str
    actor_id: str
    actor_type: ActorType
    effective_customer_id: int
    tool_name: str
    arguments: dict[str, Any]
    risk_level: int
    created_at: datetime
    status: PendingActionStatus = PendingActionStatus.PENDING


class PolicyDecision(BaseModel):
    outcome: PolicyOutcome
    tool_name: str
    risk_level: int
    reasons: list[str] = Field(default_factory=list)
    required_conditions: list[str] = Field(default_factory=list)


class PolicyAuditEvent(BaseModel):
    agent_run_id: str
    request_id: str
    conversation_id: str
    actor_id: str
    actor_type: ActorType
    roles: list[str]
    effective_customer_id: int
    action_id: str | None
    tool_name: str
    risk_level: int
    policy_outcome: PolicyOutcome
    reason_codes: list[str]
    timestamp: datetime
