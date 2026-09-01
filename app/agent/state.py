import operator
from typing import Annotated, Literal, TypedDict

from app.agent.decision_compiler import CompiledDecision
from app.agent.schemas import (
    AgentErrorCategory,
    AgentExecutionMode,
    AgentProposal,
    AgentRequestType,
    Intent,
    ProviderRunMetadata,
    SemanticDecision,
)
from app.core.context import ExecutionContext
from app.memory.schemas import MemoryCandidate
from app.policies.models import PendingAction, PolicyDecision


class ConversationMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


WorkflowLifecycleState = Literal[
    "active",
    "waiting_confirmation",
    "suspended",
    "superseded",
    "completed",
    "cancelled",
]


class SuspendedWorkflowState(TypedDict, total=False):
    """Bounded workflow snapshot; it contains no prompts or hidden reasoning."""

    intent: Intent
    pending_action: PendingAction | None
    pending_workflow_decision: SemanticDecision | None
    collected_entities: dict[str, str | int | bool]
    tool_arguments: dict[str, object]
    missing_required_fields: list[str]
    validation_context: dict[str, object]
    policy_inputs: dict[str, object]
    source_state: WorkflowLifecycleState
    workflow_id: str
    superseded_by: str | None


class AgentState(TypedDict, total=False):
    execution_context: (
        ExecutionContext  # Context của execution(lookup, order,refund, hỏi đáp, memory,..)
    )
    conversation_id: str
    conversation_tenant_id: str  # Tenant ID
    conversation_customer_id: int  # Customer ID(Khách hàng đang chat)
    conversation_actor_id: str  # Actor ID(Người dùng đang chat)
    conversation_actor_type: str  # Actor Type(kiểu người dùng đang chat)
    messages: Annotated[list[ConversationMessage], operator.add]  # Lịch sử chat
    intent: Intent  # Mục tiêu của người dùng(lookup, order,refund, hỏi đáp, memory,..)
    request_type: AgentRequestType  # Loại yêu cầu của người dùng(đọc/ghi/knowledge)
    semantic_decision: (
        SemanticDecision | None
    )  # Quyết định của agent(lookup, order,refund, hỏi đáp, memory,..)
    compile_result: (
        CompiledDecision | None
    )  # Kết quả biên dịch của agent(lookup, order,refund, hỏi đáp, memory,..)
    grounding_status: str  # Trạng thái grounding(success, failed, pending)
    grounding_reference_type: str | None  # Loại reference của grounding(knowledge, document,..)
    grounding_trusted_source: str | None  # Nguồn tin cậy của grounding(knowledge, document,..)
    target_validation_status: str  # Trạng thái validation của target(success, failed, pending)
    selected_tool: (
        str | None
    )  # Công cụ được chọn để thực hiện(lookup, order,refund, hỏi đáp, memory,..)
    tool_arguments: dict[str, object]  # Tham số của công cụ
    tool_result: dict[str, object] | None  # Kết quả của công cụ
    pending_action: (
        PendingAction | None
    )  # Hành động đang chờ(lookup, order,refund, hỏi đáp, memory,..)
    policy_decision: (
        PolicyDecision | None
    )  # Quyết định của policy(lookup, order,refund, hỏi đáp, memory,..)
    confirmation_status: str | None  # Trạng thái xác nhận của hành động(success, failed, pending)
    action_id: str | None  # ID của hành động
    requires_retrieval: bool  # Có cần retrieval không
    knowledge_query: str | None  # Câu hỏi knowledge
    retrieved_chunks: list[dict[str, object]]  # Chunks retrieved
    retrieval_metadata: dict[str, object]  # Metadata của retrieval
    answer_grounding: dict[str, object]  # Kết quả grounding của answer
    knowledge_answer: str | None  # Câu trả lời của knowledge
    citations: list[dict[str, object]]  # Danh sách citations
    retry_count: int  # Số lần retry
    last_error: str | None  # Lỗi cuối cùng
    error_category: (
        AgentErrorCategory | None
    )  # Loại lỗi của agent(lookup, order,refund, hỏi đáp, memory,..)
    decision_reason: (
        str | None
    )  # Lý do quyết định của agent(lookup, order,refund, hỏi đáp, memory,..)
    final_response: str  # Câu trả lời cuối cùng của agent(lookup, order,refund, hỏi đáp, memory,..)
    agent_run_id: str  # ID của agent(lookup, order,refund, hỏi đáp, memory,..)
    tool_execution_status: str | None  # Trạng thái execution của tool(success, failed, pending)
    memory_context: list[
        dict[str, object]
    ]  # Context của memory(lookup, order,refund, hỏi đáp, memory,..)
    memory_candidate: (
        MemoryCandidate | None
    )  # Candidate của memory(lookup, order,refund, hỏi đáp, memory,..)
    memory_key: str | None  # Key của memory(lookup, order,refund, hỏi đáp, memory,..)
    memory_operation_status: str | None  # Trạng thái operation của memory(success, failed, pending)
    memory_policy_outcome: str | None  # Kết quả policy của memory(success, failed, pending)
    failure_category: str | None  # Loại lỗi của agent(lookup, order,refund, hỏi đáp, memory,..)
    degraded_components: list[
        str
    ]  # Danh sách các component bị lỗi(lookup, order,refund, hỏi đáp, memory,..)
    recovery_action: (
        str | None
    )  # Hành động khôi phục của agent(lookup, order,refund, hỏi đáp, memory,..)
    write_outcome_unknown: bool  # Có viết outcome unknown không
    replay_detected: bool  # Có replay detected không
    idempotency_outcome: (
        str | None
    )  # Kết quả idempotency của agent(lookup, order,refund, hỏi đáp, memory,..)
    execution_mode: (
        AgentExecutionMode  # Chế độ execution của agent(lookup, order,refund, hỏi đáp, memory,..)
    )
    provider: str  # Provider của agent(lookup, order,refund, hỏi đáp, memory,..)
    model: str | None  # Model của agent(lookup, order,refund, hỏi đáp, memory,..)
    fallback_message: (
        str | None
    )  # Câu trả lời fallback của agent(lookup, order,refund, hỏi đáp, memory,..)
    proposal: AgentProposal | None  # Proposal của agent(lookup, order,refund, hỏi đáp, memory,..)
    provider_metadata: (
        ProviderRunMetadata | None
    )  # Metadata của provider(lookup, order,refund, hỏi đáp, memory,..)
    security_signal: (
        str | None
    )  # Tín hiệu security của agent(lookup, order,refund, hỏi đáp, memory,..)
    memory_security_signal: (
        str | None
    )  # Tín hiệu security của memory(lookup, order,refund, hỏi đáp, memory,..)
    memory_summary_requested: bool  # Có summary requested không
    previous_intent: (
        Intent | None
    )  # Mục tiêu trước đó của người dùng(lookup, order,refund, hỏi đáp, memory,..)
    pending_workflow_decision: (
        SemanticDecision | None
    )  # Quyết định workflow của agent(lookup, order,refund, hỏi đáp, memory,..)
    missing_required_fields: list[
        str
    ]  # Danh sách các field bị thiếu(lookup, order,refund, hỏi đáp, memory,..)
    collected_entities: dict[
        str, str | int | bool
    ]  # Danh sách các entity đã thu thập(lookup, order,refund, hỏi đáp, memory,..)
    workflow_active: bool  # Có workflow active không
    workflow_resume_status: str | None  # Trạng thái resume của workflow(success, failed, pending)
    workflow_state: WorkflowLifecycleState  # Trạng thái workflow(active, waiting_confirmation, suspended, superseded, completed, cancelled)
    workflow_interruption_pending: bool  # Có interruption pending không
    workflow_interruption_status: (
        str | None
    )  # Trạng thái interruption của workflow(success, failed, pending)
    previous_workflow_intent: (
        Intent | None
    )  # Mục tiêu trước đó của workflow(lookup, order,refund, hỏi đáp, memory,..)
    interruption_intent: (
        Intent | None
    )  # Mục tiêu interruption của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_resume_source: (
        str | None
    )  # Nguồn resume của workflow(lookup, order,refund, hỏi đáp, memory,..)
    suspended_workflow: (
        SuspendedWorkflowState | None
    )  # Trạng thái suspended của workflow(lookup, order,refund, hỏi đáp, memory,..)
    superseded_workflow: (
        SuspendedWorkflowState | None
    )  # Trạng thái superseded của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_id: str | None  # ID của workflow(lookup, order,refund, hỏi đáp, memory,..)
    previous_workflow_id: (
        str | None
    )  # ID của workflow trước đó(lookup, order,refund, hỏi đáp, memory,..)
    superseded_by: (
        str | None
    )  # ID của workflow đã superseded(lookup, order,refund, hỏi đáp, memory,..)
    workflow_transition: (
        str | None
    )  # Trạng thái transition của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_interruption_type: (
        str | None
    )  # Loại interruption của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_tool_arguments: dict[
        str, object
    ]  # Tham số của công cụ của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_validation_context: dict[
        str, object
    ]  # Context của validation của workflow(lookup, order,refund, hỏi đáp, memory,..)
    workflow_policy_inputs: dict[
        str, object
    ]  # Tham số của policy của workflow(lookup, order,refund, hỏi đáp, memory,..)
    pending_action_restored: bool  # Có pending action restored không
    restored_fields_count: int  # Số lần restored fields
    compilation_resumed: bool  # Có compilation resumed không
    original_policy_inputs_hash: (
        str  # Hash của policy inputs ban đầu(lookup, order,refund, hỏi đáp, memory,..)
    )
    restored_policy_inputs_hash: (
        str  # Hash của policy inputs đã restored(lookup, order,refund, hỏi đáp, memory,..)
    )
    policy_input_diff: str  # Sự khác biệt giữa policy inputs ban đầu và đã restored(lookup, order,refund, hỏi đáp, memory,..)
    original_pending_policy_inputs: (
        str  # Policy inputs ban đầu(lookup, order,refund, hỏi đáp, memory,..)
    )
    restored_policy_inputs: (
        str  # Policy inputs đã restored(lookup, order,refund, hỏi đáp, memory,..)
    )
    original_policy_inputs_normalized: (
        str  # Policy inputs ban đầu đã normalized(lookup, order,refund, hỏi đáp, memory,..)
    )
    restored_policy_inputs_normalized: (
        str  # Policy inputs đã restored đã normalized(lookup, order,refund, hỏi đáp, memory,..)
    )
    policy_revalidation_stage: (
        str  # Trạng thái revalidation của policy(lookup, order,refund, hỏi đáp, memory,..)
    )
    policy_revalidation_result: (
        str  # Kết quả revalidation của policy(lookup, order,refund, hỏi đáp, memory,..)
    )
    proposed_write: dict[str, object] | None
    write_blocked: bool
    situation: dict[str, str]
    handling_recommendation: dict[str, object]
    offer_pending_write: bool
