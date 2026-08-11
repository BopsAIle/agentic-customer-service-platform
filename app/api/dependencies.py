from uuid import uuid4

from fastapi import Depends

from app.agent.schemas import AgentChatRequest
from app.auth.dependencies import get_current_principal, resolve_customer_scope
from app.auth.models import Principal
from app.core.context import ExecutionContext


def get_execution_context(
    request: AgentChatRequest,
    principal: Principal = Depends(get_current_principal),
) -> ExecutionContext:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    return ExecutionContext(
        request_id=str(uuid4()),
        conversation_id=request.conversation_id,
        principal=principal,
        effective_customer_id=customer_scope.customer_id,
    )
