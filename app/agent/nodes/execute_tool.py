from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.nodes.common import error_category, serialise_result
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.agent.tool_catalog import get_agent_tool_definition
from app.resilience.config import ResilienceConfig
from app.resilience.errors import ResilienceError, RetryExhaustedError, UnknownWriteOutcomeError
from app.resilience.retry import run_with_retry
from app.tools import registry
from app.tools.base import ToolError


def make_execute_tool_node(
    session: Session, resilience_config: ResilienceConfig | None = None
) -> Callable[[AgentState], AgentState]:
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
        context = state.get("execution_context")
        if context is None:
            return {
                "last_error": "Authenticated execution context is required.",
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "tool_execution_status": "failed",
            }
        try:
            arguments = definition.input_model.model_validate(state.get("tool_arguments", {}))
            requested_customer = getattr(arguments, "customer_id", None)
            if requested_customer != context.effective_customer_id:
                return {
                    "last_error": "Tool customer scope conflicts with execution context.",
                    "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
                    "tool_execution_status": "failed",
                }
            operation_type = registry.get_tool(tool_name).operation_type.value

            def attempt() -> object:
                try:
                    result = definition.execute(session, context, arguments)
                    if operation_type == "write":
                        session.commit()
                    return result
                except Exception:
                    session.rollback()
                    raise

            result = run_with_retry(
                attempt,
                dependency="tool",
                operation_type=operation_type,
                config=resilience_config,
            )
            return {
                "tool_result": serialise_result(result),
                "tool_execution_status": "executed",
                "last_error": None,
                "error_category": None,
            }
        except UnknownWriteOutcomeError:
            return {
                "last_error": "The write outcome could not be confirmed.",
                "error_category": AgentErrorCategory.DEPENDENCY_FAILURE,
                "failure_category": "tool_timeout",
                "recovery_action": "no_replay",
                "write_outcome_unknown": True,
                "tool_execution_status": "failed",
            }
        except RetryExhaustedError as error:
            return {
                "last_error": "The selected dependency could not be reached reliably.",
                "error_category": AgentErrorCategory.DEPENDENCY_FAILURE,
                "failure_category": error.category.value,
                "recovery_action": "fail_safely",
                "tool_execution_status": "failed",
            }
        except ResilienceError as error:
            return {
                "last_error": "The selected dependency could not be reached reliably.",
                "error_category": AgentErrorCategory.DEPENDENCY_FAILURE,
                "failure_category": error.category.value,
                "recovery_action": "fail_safely",
                "tool_execution_status": "failed",
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
