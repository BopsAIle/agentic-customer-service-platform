import operator
from typing import Annotated, Literal, TypedDict

from app.agent.decision_compiler import CompiledDecision
from app.agent.schemas import (
    AgentErrorCategory,
    AgentRequestType,
    Intent,
    SemanticDecision,
)
from app.core.context import ExecutionContext
from app.memory.schemas import MemoryCandidate
from app.policies.models import PendingAction, PolicyDecision


class ConversationMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class AgentState(TypedDict, total=False):
    execution_context: ExecutionContext
    conversation_id: str
    conversation_customer_id: int
    conversation_actor_id: str
    conversation_actor_type: str
    messages: Annotated[list[ConversationMessage], operator.add]
    intent: Intent
    request_type: AgentRequestType
    semantic_decision: SemanticDecision | None
    compile_result: CompiledDecision | None
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
    retrieval_metadata: dict[str, object]
    knowledge_answer: str | None
    citations: list[dict[str, object]]
    retry_count: int
    last_error: str | None
    error_category: AgentErrorCategory | None
    decision_reason: str | None
    final_response: str
    agent_run_id: str
    tool_execution_status: str | None
    memory_context: list[dict[str, object]]
    memory_candidate: MemoryCandidate | None
    memory_key: str | None
    memory_operation_status: str | None
    memory_policy_outcome: str | None
    failure_category: str | None
    degraded_components: list[str]
    recovery_action: str | None
    write_outcome_unknown: bool
