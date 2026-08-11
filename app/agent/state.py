import operator
from typing import Annotated, Literal, TypedDict

from app.agent.schemas import (
    AgentErrorCategory,
    AgentRequestType,
    Intent,
)
from app.policies.models import PendingAction, PolicyDecision


class ConversationMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class AgentState(TypedDict, total=False):
    conversation_id: str
    customer_id: int
    conversation_customer_id: int
    messages: Annotated[list[ConversationMessage], operator.add]
    intent: Intent
    request_type: AgentRequestType
    selected_tool: str | None
    tool_arguments: dict[str, object]
    tool_result: dict[str, object] | None
    pending_action: PendingAction | None
    policy_decision: PolicyDecision | None
    confirmation_status: str | None
    action_id: str | None
    requires_retrieval: bool
    knowledge_query: str | None
    retrieved_chunks: list[dict[str, object]]
    knowledge_answer: str | None
    citations: list[dict[str, object]]
    retry_count: int
    last_error: str | None
    error_category: AgentErrorCategory | None
    decision_reason: str | None
    final_response: str
    agent_run_id: str
    tool_execution_status: str | None
