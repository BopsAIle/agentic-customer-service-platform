from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.schemas import AgentRequestType, Intent, StructuredDecision


class ScenarioTurn(BaseModel):
    user: str = Field(min_length=1)
    advance_seconds: int = Field(default=0, ge=0)


class ExpectedState(BaseModel):
    order_id: int | None = None
    order_status: str | None = None
    escalation_count: int | None = None
    ticket_count: int | None = None


class ScenarioExpectation(BaseModel):
    intent: Intent | None = None
    request_type: AgentRequestType | None = None
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_arguments: dict[str, Any] = Field(default_factory=dict)
    pending_tool: str | None = None
    executed_tool: str | None = None
    requires_confirmation: bool = False
    confirmation_required: bool | None = None
    unauthorized_action: bool = False
    escalation_required: bool = False
    expected_final_state: ExpectedState | None = None
    completion: Literal[
        "response", "citation", "state", "pending", "escalation", "safe_failure"
    ] = "response"
    response_contains: list[str] = Field(default_factory=list)
    memory_status: str | None = None
    memory_key: str | None = None
    memory_count: int | None = None
    memory_visible_contains: list[str] = Field(default_factory=list)
    memory_visible_not_contains: list[str] = Field(default_factory=list)
    failure_behavior: Literal["recover", "clarify", "deny", "escalate", "safe_failure"] | None = (
        None
    )
    critical_safety: bool = False


class FaultSpec(BaseModel):
    kind: Literal[
        "tool_timeout", "tool_error", "malformed_decision", "retriever_empty", "retriever_error"
    ]
    tool: str | None = None
    once: bool = True


class EvaluationScenario(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=1)
    category: str
    conversation: list[ScenarioTurn] = Field(min_length=1)
    customer_id: int = Field(gt=0)
    decisions: list[StructuredDecision] = Field(default_factory=list)
    expect: ScenarioExpectation
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    fault: FaultSpec | None = None
    seed_memory_records: list[dict[str, Any]] = Field(default_factory=list)


class ScenarioResult(BaseModel):
    scenario_id: str
    category: str
    passed: bool
    intent_correct: bool | None = None
    request_type_correct: bool | None = None
    selected_tools: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    pending_action: str | None = None
    tool_arguments_correct: bool | None = None
    confirmation_compliant: bool | None = None
    unauthorized_action: bool = False
    escalation_correct: bool | None = None
    citations_valid: bool | None = None
    task_completed: bool = False
    failure_behavior: str | None = None
    memory_retrieval_correct: bool | None = None
    memory_write_policy_compliant: bool | None = None
    memory_conflict_correct: bool | None = None
    latency_ms: float = 0.0
    failure_reasons: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    seed: int
    dataset: str
    started_at: str
    finished_at: str
    scenario_count: int
    results: list[ScenarioResult]
    metrics: dict[str, float]
    category_breakdown: dict[str, dict[str, float]]
