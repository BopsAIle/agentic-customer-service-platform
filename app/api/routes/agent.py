from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentChatRequest, AgentResponse
from app.api.dependencies import get_execution_context
from app.api.errors import raise_http_for_tool_error
from app.core.context import ExecutionContext
from app.core.database import get_db
from app.resilience.errors import RateLimitExceededError
from app.tools.base import ToolError

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_runtime(request: Request) -> AgentRuntime:
    runtime: AgentRuntime = request.app.state.agent_runtime
    return runtime


@router.post("/chat", response_model=AgentResponse)
def chat(
    request: AgentChatRequest,
    execution_context: ExecutionContext = Depends(get_execution_context),
    session: Session = Depends(get_db),
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentResponse:
    try:
        if request.execution_mode.value == "recorded_replay":
            return runtime.run(
                context=execution_context,
                message=request.message,
                session=session,
            )
        return runtime.run(
            context=execution_context,
            message=request.message,
            session=session,
            execution_mode=request.execution_mode,
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate limit exceeded.",
            headers={"Retry-After": str(max(1, int(error.retry_after_seconds)))},
        ) from None
    except ToolError as error:
        raise_http_for_tool_error(error)
