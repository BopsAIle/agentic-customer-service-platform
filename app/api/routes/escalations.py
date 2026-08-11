from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error, raise_http_for_unknown_write
from app.api.idempotency import get_idempotency_key
from app.auth.dependencies import require_support_operator, resolve_customer_scope
from app.auth.models import Principal
from app.core.database import get_db
from app.resilience.errors import UnknownWriteOutcomeError
from app.schemas.domain import EscalationResponse
from app.services.idempotency import IdempotencyScope, commit_business_write
from app.tools.base import ToolError
from app.tools.escalation import EscalateToHumanInput, escalate_to_human

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.post("", response_model=EscalationResponse, status_code=201)
def create_escalation(
    request: EscalateToHumanInput,
    idempotency_key: str = Depends(get_idempotency_key),
    principal: Principal = Depends(require_support_operator),
    session: Session = Depends(get_db),
) -> EscalationResponse:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        result = escalate_to_human(
            session,
            request.model_copy(update={"customer_id": customer_scope.customer_id}),
            idempotency=IdempotencyScope(actor_id=principal.actor_id, key=idempotency_key),
        )
        commit_business_write(session, "escalate_to_human")
        return result
    except UnknownWriteOutcomeError as error:
        raise_http_for_unknown_write(error)
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
