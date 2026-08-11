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
    conversation_id: str
    customer_id: int
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
    trace: list[UITraceEvent] = Field(default_factory=list)


class ConversationView(BaseModel):
    conversation_id: str
    customer_id: int
    run_count: int
    runs: list[AgentRunView]
    messages: list[UIMessageView]


class MemoryView(BaseModel):
    id: int
    memory_type: str
    normalized_key: str
    content: str
    status: str
    created_at: datetime
    expires_at: datetime | None = None


class SystemComponentHealth(BaseModel):
    name: str
    status: str
    detail: str


class SystemHealthView(BaseModel):
    status: str
    components: list[SystemComponentHealth]
