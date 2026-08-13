from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.decision_compiler import (
    BusinessTargetResolver,
    CompileStatus,
    DecisionCompiler,
)
from app.agent.schemas import AgentErrorCategory, SemanticDecision
from app.agent.state import AgentState
from app.observability.tracing import span


def make_compile_decision_node(session: Session) -> Callable[[AgentState], AgentState]:
    compiler = DecisionCompiler(BusinessTargetResolver(session))

    def compile_decision(state: AgentState) -> AgentState:
        decision = state.get("semantic_decision")
        if decision is None:
            return {}
        assert isinstance(decision, SemanticDecision)
        result = compiler.compile(decision, state["execution_context"])
        with span(
            "decision.compile",
            attributes={
                "decision.contract.version": "semantic_decision_v2",
                "semantic.intent": decision.intent.value,
                "compiler.status": result.status.value,
                "compiled.tool": result.selected_tool or "none",
            },
        ):
            pass
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
            "error_category": None,
            "last_error": None,
        }

    return compile_decision
