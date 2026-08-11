from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentChatRequest, AgentResponse
from app.api.errors import raise_http_for_tool_error
from app.auth.dependencies import get_current_principal, resolve_customer_scope
from app.auth.models import Principal
from app.core.database import get_db
from app.tools.base import ToolError

router = APIRouter(prefix="/agent", tags=["agent"])
_runtime = AgentRuntime()


def get_agent_runtime() -> AgentRuntime:
    return _runtime


@router.post("/chat", response_model=AgentResponse)
def chat(
    request: AgentChatRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentResponse:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        return runtime.run(
            conversation_id=request.conversation_id,
            customer_id=customer_scope.customer_id,
            message=request.message,
            session=session,
        )
    except ToolError as error:
        raise_http_for_tool_error(error)
