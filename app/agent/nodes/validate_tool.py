from pydantic import ValidationError as PydanticValidationError

from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.agent.tool_catalog import get_agent_tool_definition


def validate_tool(state: AgentState) -> AgentState:
    tool_name = state.get("selected_tool")
    if not tool_name or state.get("error_category") is not None:
        return {}
    definition = get_agent_tool_definition(tool_name)
    if definition is None:
        return {
            "last_error": f"Tool {tool_name} is not registered.",
            "error_category": AgentErrorCategory.UNKNOWN_TOOL,
        }
    raw_arguments = dict(state.get("tool_arguments", {}))
    if tool_name in {"get_order", "get_ticket"} and raw_arguments.get("customer_id") is None:
        raw_arguments["customer_id"] = state["customer_id"]
    try:
        arguments = definition.input_model.model_validate(raw_arguments)
    except PydanticValidationError:
        return {
            "last_error": "The selected tool arguments were invalid.",
            "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
        }
    arguments_data = arguments.model_dump(mode="json")
    requested_customer = arguments_data.get("customer_id")
    if requested_customer is not None and requested_customer != state.get("customer_id"):
        return {
            "last_error": "The selected resource does not belong to this customer.",
            "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
        }
    return {"tool_arguments": arguments_data}
