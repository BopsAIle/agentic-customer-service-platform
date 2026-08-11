from app.agent.schemas import AgentErrorCategory, AgentRequestType, Intent
from app.agent.state import AgentState


def select_tool(state: AgentState) -> AgentState:
    if state.get("error_category") is not None:
        return {}
    request_type = state.get("request_type")
    if request_type in {
        AgentRequestType.INFORMATIONAL,
        AgentRequestType.UNCLEAR,
        AgentRequestType.KNOWLEDGE_ONLY,
    }:
        return {"selected_tool": None, "tool_arguments": {}}
    if state.get("intent") in {Intent.MEMORY_REMEMBER, Intent.MEMORY_FORGET}:
        return {"selected_tool": None, "tool_arguments": {}}
    if not state.get("selected_tool"):
        return {
            "last_error": "No registered tool was selected for this request.",
            "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
        }
    return {}
