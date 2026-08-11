from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agent.nodes.common import error_category, serialise_result
from app.agent.schemas import AgentErrorCategory
from app.agent.state import AgentState
from app.agent.tool_catalog import get_agent_tool_definition
from app.resilience.errors import UnknownWriteOutcomeError
from app.services.idempotency import IdempotencyScope, commit_business_write
from app.tools.base import ToolError


def make_human_escalation_node(session: Session) -> Callable[[AgentState], AgentState]:
    def execute_human_escalation(state: AgentState) -> AgentState:
        if state.get("selected_tool") != "escalate_to_human":
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Only the registered escalation tool may use the human path.",
                "tool_execution_status": "failed",
            }
        definition = get_agent_tool_definition("escalate_to_human")
        if definition is None:
            return {
                "error_category": AgentErrorCategory.UNKNOWN_TOOL,
                "last_error": "Escalation tool is not registered.",
                "tool_execution_status": "failed",
            }
        context = state.get("execution_context")
        if context is None:
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "Authenticated execution context is required.",
                "tool_execution_status": "failed",
            }
        try:
            arguments = definition.input_model.model_validate(state.get("tool_arguments", {}))
            requested_customer = getattr(arguments, "customer_id", None)
            if requested_customer != context.effective_customer_id:
                return {
                    "error_category": AgentErrorCategory.OWNERSHIP_VIOLATION,
                    "last_error": "Tool customer scope conflicts with execution context.",
                    "tool_execution_status": "failed",
                }
            action_id = state.get("action_id")
            if not action_id:
                return {
                    "error_category": AgentErrorCategory.POLICY_DENIED,
                    "last_error": "Business write is missing its idempotency key.",
                    "tool_execution_status": "failed",
                }
            result = definition.execute(
                session,
                context,
                arguments,
                IdempotencyScope(actor_id=context.principal.actor_id, key=action_id),
            )
            commit_business_write(session, "escalate_to_human")
            return {
                "tool_result": serialise_result(result),
                "tool_execution_status": "executed",
                "error_category": None,
                "last_error": None,
            }
        except UnknownWriteOutcomeError:
            return {
                "error_category": AgentErrorCategory.DEPENDENCY_FAILURE,
                "last_error": "The escalation outcome could not be confirmed.",
                "failure_category": "tool_timeout",
                "recovery_action": "no_replay",
                "write_outcome_unknown": True,
                "tool_execution_status": "failed",
            }
        except ToolError as error:
            session.rollback()
            return {
                "error_category": error_category(error),
                "last_error": str(error),
                "tool_execution_status": "failed",
            }
        except Exception:
            session.rollback()
            return {
                "error_category": AgentErrorCategory.POLICY_DENIED,
                "last_error": "The human escalation path could not be completed.",
                "tool_execution_status": "failed",
            }

    return execute_human_escalation
