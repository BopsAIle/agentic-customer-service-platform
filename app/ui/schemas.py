from datetime import datetime

from pydantic import BaseModel, Field


class UIMessageView(BaseModel):
    role: str
    content_available: bool
    content: str | None = None


class UIToolEvent(BaseModel):
    name: str
    risk_level: int | None = None
    status: str
    duration_ms: float
    result_fields: list[str] = Field(default_factory=list)


class UIPolicyEvent(BaseModel):
    event_id: str = ""
    request_id: str = ""
    conversation_id: str = ""
    timestamp: datetime | None = None
    stage: str = "policy_evaluation"
    confirmation_status: str | None = None
    revalidation: bool = False
    execution_status: str | None = None
    actor_id: str
    actor_type: str
    roles: list[str] = Field(default_factory=list)
    effective_customer_id: int
    tool_name: str
    risk_level: int
    outcome: str
    reason_codes: list[str] = Field(default_factory=list)


class UIRagDocument(BaseModel):
    citation_id: str
    title: str
    section: str
    source: str
    score: float


class UIRetrievalMetadata(BaseModel):
    backend: str = "unknown"
    embedding_provider: str = "unknown"
    reranker_enabled: bool = False
    retrieval_count: int = 0
    latency_seconds: float = 0.0
    fallback_status: str = "none"
    hybrid: bool = False
    fusion_strategy: str = "none"
    dense_candidate_count: int = 0
    sparse_candidate_count: int = 0


class UIMemoryUsage(BaseModel):
    item_count: int
    keys: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)


class UITraceEvent(BaseModel):
    name: str
    status: str
    duration_ms: float
    timestamp: datetime


class AgentRunView(BaseModel):
    run_id: str
    request_id: str
    conversation_id: str
    customer_id: int
    actor_id: str
    actor_type: str
    roles: list[str] = Field(default_factory=list)
    intent: str
    request_type: str
    status: str
    started_at: datetime
    duration_ms: float
    trace_id: str | None = None
    path: list[str] = Field(default_factory=list)
    failure_category: str | None = None
    degraded_components: list[str] = Field(default_factory=list)
    recovery_action: str | None = None
    memory: UIMemoryUsage
    tools: list[UIToolEvent] = Field(default_factory=list)
    policy: list[UIPolicyEvent] = Field(default_factory=list)
    rag_documents: list[UIRagDocument] = Field(default_factory=list)
    retrieval_metadata: UIRetrievalMetadata = Field(default_factory=UIRetrievalMetadata)
    trace: list[UITraceEvent] = Field(default_factory=list)


class ConversationView(BaseModel):
    conversation_id: str
    customer_id: int
    run_count: int
    runs: list[AgentRunView]
    messages: list[UIMessageView]


class MemoryView(BaseModel):
    id: int
    customer_id: int
    memory_type: str
    normalized_key: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class SystemComponentHealth(BaseModel):
    name: str
    status: str
    detail: str


class SystemHealthView(BaseModel):
    status: str
    components: list[SystemComponentHealth]
