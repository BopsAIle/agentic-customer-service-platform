from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Customer, Order, SupportTicket, TicketStatus
from app.schemas.domain import TicketResponse
from app.services.idempotency import IdempotencyScope, execute_idempotent
from app.services.ticket_service import get_ticket_for_customer
from app.tools.base import OwnershipError, ResourceNotFoundError


class GetTicketInput(BaseModel):
    ticket_id: int = Field(gt=0)
    customer_id: int = Field(gt=0)


class CreateSupportTicketInput(BaseModel):
    customer_id: int = Field(gt=0)
    order_id: int | None = Field(default=None, gt=0)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)


def get_ticket(session: Session, request: GetTicketInput) -> TicketResponse:
    ticket = get_ticket_for_customer(session, request.ticket_id, request.customer_id)
    if ticket is None:
        raise ResourceNotFoundError("Support ticket", request.ticket_id)
    return TicketResponse.model_validate(ticket)


def create_support_ticket(
    session: Session,
    request: CreateSupportTicketInput,
    *,
    idempotency: IdempotencyScope,
) -> TicketResponse:
    def load_result(ticket_id: int) -> TicketResponse:
        ticket = session.get(SupportTicket, ticket_id)
        if ticket is None:
            raise ResourceNotFoundError("Support ticket", ticket_id)
        return TicketResponse.model_validate(ticket)

    def perform() -> tuple[TicketResponse, int]:
        if session.get(Customer, request.customer_id) is None:
            raise ResourceNotFoundError("Customer", request.customer_id)
        if request.order_id is not None:
            order = session.get(Order, request.order_id)
            if order is None:
                raise ResourceNotFoundError("Order", request.order_id)
            if order.customer_id != request.customer_id:
                raise OwnershipError("Order", request.order_id, request.customer_id)
        ticket = SupportTicket(
            customer_id=request.customer_id,
            order_id=request.order_id,
            category=request.category,
            status=TicketStatus.OPEN,
            description=request.description,
        )
        session.add(ticket)
        session.flush()
        return TicketResponse.model_validate(ticket), ticket.id

    return execute_idempotent(
        session,
        scope=idempotency,
        operation="create_support_ticket",
        customer_id=request.customer_id,
        request_payload=request.model_dump(mode="json"),
        perform=perform,
        load_result=load_result,
    )
