from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error
from app.auth.dependencies import require_support_operator, resolve_customer_scope
from app.auth.models import Principal
from app.core.database import get_db
from app.schemas.domain import EscalationResponse
from app.tools.base import ToolError
from app.tools.escalation import EscalateToHumanInput, escalate_to_human

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.post("", response_model=EscalationResponse, status_code=201)
def create_escalation(
    request: EscalateToHumanInput,
    principal: Principal = Depends(require_support_operator),
    session: Session = Depends(get_db),
) -> EscalationResponse:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        result = escalate_to_human(
            session,
            request.model_copy(update={"customer_id": customer_scope.customer_id}),
        )
        session.commit()
        return result
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
