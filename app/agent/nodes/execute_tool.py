from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.nodes.common import error_category, serialise_result
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.agent.tool_catalog import get_agent_tool_definition
from app.tools import registry
from app.tools.base import ToolError


def make_execute_tool_node(session: Session) -> Callable[[AgentState], AgentState]:
    def execute_tool(state: AgentState) -> AgentState:
        tool_name = state["selected_tool"]
        if tool_name is None:
            return {
                "last_error": "No tool was selected.",
                "error_category": AgentErrorCategory.INVALID_TOOL_ARGUMENTS,
                "tool_execution_status": "failed",
            }
        definition = get_agent_tool_definition(tool_name)
        if definition is None:
            return {
                "last_error": f"Tool {tool_name} is not registered.",
                "error_category": AgentErrorCategory.UNKNOWN_TOOL,
                "tool_execution_status": "failed",
            }
        try:
            arguments = definition.input_model.model_validate(state.get("tool_arguments", {}))
            result = definition.execute(session, arguments)
            if registry.get_tool(tool_name).operation_type.value == "write":
                session.commit()
            return {
                "tool_result": serialise_result(result),
                "tool_execution_status": "executed",
                "last_error": None,
                "error_category": None,
            }
        except ToolError as error:
            session.rollback()
            return {
                "last_error": str(error),
                "error_category": error_category(error),
                "tool_execution_status": "failed",
            }
        except Exception:
            session.rollback()
            return {
                "last_error": "The selected tool could not be executed.",
                "error_category": AgentErrorCategory.LLM_ERROR,
                "tool_execution_status": "failed",
            }

    return execute_tool
