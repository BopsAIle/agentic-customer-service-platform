from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.policies.models import PendingAction
from app.rag.schemas import Citation


class Intent(StrEnum):
    CUSTOMER_LOOKUP = "customer_lookup"
    ORDER_LOOKUP = "order_lookup"
    ORDER_LIST = "order_list"
    TICKET_LOOKUP = "ticket_lookup"
    TICKET_LIST = "ticket_list"
    TICKET_CREATE = "ticket_create"
    ORDER_CANCEL = "order_cancel"
    REFUND_REQUEST = "refund_request"
    HUMAN_ESCALATION = "human_escalation"
    CAPABILITY_QUESTION = "capability_question"
    REFUND_POLICY = "refund_policy"
    CANCELLATION_POLICY = "cancellation_policy"
    SHIPPING_POLICY = "shipping_policy"
    SUPPORT_FAQ = "support_faq"
    REFUND_ELIGIBILITY = "refund_eligibility"
    CANCELLATION_EXPLANATION = "cancellation_explanation"
    UNKNOWN = "unknown"


class AgentRequestType(StrEnum):
    INFORMATIONAL = "informational"
    READ_ACTION = "read_action"
    WRITE_ACTION = "write_action"
    ESCALATION = "escalation"
    UNCLEAR = "unclear"
    KNOWLEDGE_ONLY = "knowledge_only"
    ACTION_ONLY = "action_only"
    KNOWLEDGE_AND_ACTION = "knowledge_and_action"


class AgentErrorCategory(StrEnum):
    RESOURCE_NOT_FOUND = "resource_not_found"
    OWNERSHIP_VIOLATION = "ownership_violation"
    INVALID_STATE = "invalid_state"
    DUPLICATE_ACTION = "duplicate_action"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    LLM_ERROR = "llm_error"
    POLICY_DENIED = "policy_denied"
    RETRIEVAL_ERROR = "retrieval_error"
    RERANKER_ERROR = "reranker_error"
    CONFIRMATION_EXPIRED = "confirmation_expired"


class StructuredDecision(BaseModel):
    intent: Intent
    request_type: AgentRequestType
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=300)
    requires_retrieval: bool = False
    knowledge_query: str | None = Field(default=None, max_length=500)


class AgentToolCall(BaseModel):
    name: str
    status: str
    result: dict[str, object] | None = None


class AgentResponse(BaseModel):
    conversation_id: str
    agent_run_id: str
    message: str
    intent: Intent
    request_type: AgentRequestType
    tool_call: AgentToolCall | None = None
    pending_action: PendingAction | None = None
    decision_reason: str | None = None
    error_category: AgentErrorCategory | None = None
    citations: list[Citation] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    customer_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=5000)
