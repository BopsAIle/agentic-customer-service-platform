from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentChatRequest, AgentResponse
from app.api.errors import raise_http_for_tool_error
from app.core.database import get_db
from app.tools.base import ToolError

router = APIRouter(prefix="/agent", tags=["agent"])
_runtime = AgentRuntime()


def get_agent_runtime() -> AgentRuntime:
    return _runtime


@router.post("/chat", response_model=AgentResponse)
def chat(
    request: AgentChatRequest,
    session: Session = Depends(get_db),
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentResponse:
    try:
        return runtime.run(
            conversation_id=request.conversation_id,
            customer_id=request.customer_id,
            message=request.message,
            session=session,
        )
    except ToolError as error:
        raise_http_for_tool_error(error)
