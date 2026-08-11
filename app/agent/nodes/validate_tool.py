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
    context = state.get("execution_context")
    if context is None:
        return {
            "last_error": "Authenticated execution context is required.",
            "error_category": AgentErrorCategory.POLICY_DENIED,
        }
    raw_arguments = dict(state.get("tool_arguments", {}))
    requested_customer = raw_arguments.get("customer_id")
    if requested_customer is not None and requested_customer != context.effective_customer_id:
        return {
            "last_error": "The selected resource does not belong to this customer.",
            "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
        }
    if "customer_id" in definition.input_model.model_fields:
        raw_arguments["customer_id"] = context.effective_customer_id
    try:
        arguments = definition.input_model.model_validate(raw_arguments)
    except PydanticValidationError:
        return {
            "last_error": "The selected tool arguments were invalid.",
            "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
        }
    arguments_data = arguments.model_dump(mode="json")
    return {"tool_arguments": arguments_data}
