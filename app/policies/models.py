import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.auth.models import ActorType


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_HUMAN = "require_human"
    DENY = "deny"

#PendingActionStatus là vòng đời của một hành động ghi đã bị đóng băng, chờ khách xác nhận
class PendingActionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"
"""
Policy: risk 2 → REQUIRE_CONFIRMATION
            │
            ▼
        PENDING  ── khách Yes ──► CONFIRMED ── restore + revalidate ──► EXECUTED
            │                         │                                    ▲
            │                         └── revalidate/tool fail ──────────► FAILED
            │
            ├── khách No / prompt injection ──► REJECTED
            ├── quá TTL (mặc định 300s)     ──► EXPIRED
            └── câu mơ hồ / hỏi chuyện khác ──► vẫn PENDING
"""

class PendingAction(BaseModel):
    action_id: str
    conversation_id: str
    tenant_id: str = "default"
    actor_id: str
    actor_type: ActorType
    effective_customer_id: int
    tool_name: str
    arguments: dict[str, Any]
    risk_level: int
    # Bounded workflow context captured at the confirmation boundary. Defaults keep
    # older checkpoints readable while new actions retain enough data to revalidate.
    intent: str | None = None
    collected_entities: dict[str, Any] = Field(default_factory=dict)
    validation_context: dict[str, Any] = Field(default_factory=dict)
    policy_inputs: dict[str, Any] = Field(default_factory=dict)
    policy_inputs_hash: str | None = None
    created_at: datetime
    status: PendingActionStatus = PendingActionStatus.PENDING


class PolicyDecision(BaseModel):
    outcome: PolicyOutcome
    tool_name: str
    risk_level: int
    reasons: list[str] = Field(default_factory=list)
    required_conditions: list[str] = Field(default_factory=list)


class PolicyAuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex}")
    agent_run_id: str
    request_id: str
    conversation_id: str
    tenant_id: str = "default"
    actor_id: str
    actor_type: ActorType
    roles: list[str] = Field(max_length=20)
    effective_customer_id: int
    action_id: str | None
    tool_name: str
    risk_level: int
    policy_outcome: PolicyOutcome
    reason_codes: list[str] = Field(max_length=10)
    timestamp: datetime
    stage: str = "policy_evaluation"
    confirmation_status: str | None = None
    revalidation: bool = False
    execution_status: str | None = None


def stable_policy_event_id(
    agent_run_id: str, action_id: str | None, stage: str, marker: str
) -> str:
    """Build an idempotent identity for one invocation or action lifecycle observation.

    Action-bearing lifecycle events are stable across confirmation/replay
    invocations. Events without an action remain scoped to their invocation.
    """

    identity = "|".join((action_id or agent_run_id, stage, marker))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"audit_{digest}"
