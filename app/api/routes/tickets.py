from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error, raise_http_for_unknown_write
from app.api.idempotency import get_idempotency_key
from app.auth.dependencies import (
    get_current_principal,
    require_support_operator,
    resolve_customer_scope,
)
from app.auth.models import Principal
from app.core.database import get_db
from app.resilience.errors import UnknownWriteOutcomeError
from app.schemas.domain import TicketResponse
from app.services.idempotency import IdempotencyScope, commit_business_write
from app.tools.base import ToolError
from app.tools.tickets import (
    CreateSupportTicketInput,
    GetTicketInput,
    create_support_ticket,
    get_ticket,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket_by_id(
    ticket_id: int,
    customer_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> TicketResponse:
    customer_scope = resolve_customer_scope(principal, customer_id)
    try:
        return get_ticket(
            session,
            GetTicketInput(ticket_id=ticket_id, customer_id=customer_scope.customer_id),
        )
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    request: CreateSupportTicketInput,
    idempotency_key: str = Depends(get_idempotency_key),
    principal: Principal = Depends(require_support_operator),
    session: Session = Depends(get_db),
) -> TicketResponse:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        result = create_support_ticket(
            session,
            request.model_copy(update={"customer_id": customer_scope.customer_id}),
            idempotency=IdempotencyScope(actor_id=principal.actor_id, key=idempotency_key),
        )
        commit_business_write(session, "create_support_ticket")
        return result
    except UnknownWriteOutcomeError as error:
        raise_http_for_unknown_write(error)
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
