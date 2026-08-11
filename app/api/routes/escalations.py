from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error
from app.core.database import get_db
from app.schemas.domain import EscalationResponse
from app.tools.base import ToolError
from app.tools.escalation import EscalateToHumanInput, escalate_to_human

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.post("", response_model=EscalationResponse, status_code=201)
def create_escalation(
    request: EscalateToHumanInput, session: Session = Depends(get_db)
) -> EscalationResponse:
    try:
        result = escalate_to_human(session, request)
        session.commit()
        return result
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
