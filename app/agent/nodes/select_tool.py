from app.agent.decision_compiler import ACTION_TOOLS
from app.agent.schemas import AgentRequestType, Intent
from app.agent.state import AgentState


def select_tool(state: AgentState) -> AgentState:
    """Route CSKH: gather + RAG for complaints; never execute unconfirmed writes."""

    if state.get("error_category") is not None:
        return {}
    if state.get("intent") in {Intent.MEMORY_REMEMBER, Intent.MEMORY_FORGET}:
        return {"selected_tool": None, "tool_arguments": {}}
    if state.get("memory_summary_requested"):
        return {"selected_tool": None, "tool_arguments": {}, "requires_retrieval": False}

    write_blocked = bool(state.get("write_blocked"))
    proposed_write = state.get("proposed_write")
    confirmation_status = state.get("confirmation_status")
    selected = state.get("selected_tool")
    request_type = state.get("request_type")

    if confirmation_status == "confirmed" and state.get("pending_action_restored"):
        pending = state.get("pending_action")
        if not selected and pending is not None:
            selected = pending.tool_name
        if selected:
            return {"selected_tool": selected, "requires_retrieval": False}

    if write_blocked and selected in ACTION_TOOLS.values():
        selected = None

    if proposed_write and confirmation_status != "confirmed":
        if selected in ACTION_TOOLS.values():
            selected = None
        return {
            "selected_tool": selected,
            "requires_retrieval": True,
        }

    if request_type in {
        AgentRequestType.INFORMATIONAL,
        AgentRequestType.UNCLEAR,
        AgentRequestType.KNOWLEDGE_ONLY,
    }:
        if request_type == AgentRequestType.UNCLEAR and state.get("intent") is Intent.UNKNOWN:
            return {"selected_tool": None, "tool_arguments": {}, "requires_retrieval": False}
        requires_retrieval = request_type == AgentRequestType.KNOWLEDGE_ONLY or bool(
            state.get("requires_retrieval")
        )
        if request_type == AgentRequestType.KNOWLEDGE_ONLY:
            requires_retrieval = True
        return {
            "selected_tool": None,
            "tool_arguments": {},
            "requires_retrieval": requires_retrieval,
        }

    if not selected:
        return {"requires_retrieval": True, "selected_tool": None, "tool_arguments": {}}
    return {}
