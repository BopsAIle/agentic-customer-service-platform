import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.decision_compiler import (
    BusinessTargetResolver,
    CompileStatus,
    DecisionCompiler,
)
from app.agent.schemas import AgentErrorCategory, SemanticDecision
from app.agent.semantic_grounding import validate_semantic_grounding
from app.agent.state import AgentState
from app.agent.target_admissibility import assess_target_admissibility
from app.observability.metrics import get_metrics
from app.observability.tracing import span


def make_compile_decision_node(
    session: Session, decision_contract_version: str = "semantic_decision_v2"
) -> Callable[[AgentState], AgentState]:
    compiler = DecisionCompiler(BusinessTargetResolver(session))

    def compile_decision(state: AgentState) -> AgentState:
        started = time.perf_counter()
        status = "skipped"
        decision = state.get("semantic_decision")
        if decision is None:
            get_metrics().decision_compile_duration_seconds.record(
                time.perf_counter() - started, {"status": status}
            )
            return {}
        assert isinstance(decision, SemanticDecision)
        user_message = _latest_user_message(state)
        grounding = validate_semantic_grounding(decision, user_message)
        admissibility = assess_target_admissibility(decision.intent, decision.target, grounding)
        result = compiler.compile(
            decision,
            state["execution_context"],
            grounding=grounding,
            user_message=user_message,
        )
        with span(
            "decision.compile",
            attributes={
                "decision.contract.version": decision_contract_version,
                "semantic.intent": decision.intent.value,
                "semantic.grounding.status": grounding.status.value,
                "semantic.grounding.reference_type": grounding.reference_type or "none",
                "semantic.target_admissibility": admissibility.value,
                "compiler.status": result.status.value,
                "compiled.tool": result.selected_tool or "none",
            },
        ):
            pass
        status = "rejected" if result.status == CompileStatus.COMPILE_REJECTED else "accepted"
        get_metrics().decision_compile_duration_seconds.record(
            time.perf_counter() - started, {"status": status}
        )
        if result.status == CompileStatus.COMPILE_REJECTED:
            return {
                "intent": result.intent,
                "request_type": result.request_type,
                "selected_tool": None,
                "tool_arguments": {},
                "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
                "last_error": "The semantic request could not be compiled safely.",
                "decision_reason": result.reason,
                "compile_result": result,
                "grounding_status": grounding.status.value,
                "grounding_reference_type": grounding.reference_type,
                "grounding_trusted_source": grounding.trusted_source,
                "target_validation_status": admissibility.value,
            }
        return {
            "intent": result.intent,
            "request_type": result.request_type,
            "selected_tool": result.selected_tool,
            "tool_arguments": result.tool_arguments,
            "requires_retrieval": result.requires_retrieval,
            "knowledge_query": result.knowledge_query,
            "memory_candidate": result.memory_candidate,
            "memory_key": result.memory_key,
            "decision_reason": result.reason,
            "compile_result": result,
            "grounding_status": grounding.status.value,
            "grounding_reference_type": grounding.reference_type,
            "grounding_trusted_source": grounding.trusted_source,
            "target_validation_status": admissibility.value,
            "error_category": None,
            "last_error": None,
        }

    return compile_decision


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message["role"] == "user":
            return message["content"]
    return ""
