from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error
from app.core.database import get_db
from app.schemas.domain import TicketResponse
from app.tools.base import ToolError
from app.tools.tickets import (
    CreateSupportTicketInput,
    GetTicketInput,
    create_support_ticket,
    get_ticket,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket_by_id(ticket_id: int, session: Session = Depends(get_db)) -> TicketResponse:
    try:
        return get_ticket(session, GetTicketInput(ticket_id=ticket_id))
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    request: CreateSupportTicketInput, session: Session = Depends(get_db)
) -> TicketResponse:
    try:
        result = create_support_ticket(session, request)
        session.commit()
        return result
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
