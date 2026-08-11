from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Customer, Order, SupportTicket, TicketStatus
from app.schemas.domain import TicketResponse
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


def create_support_ticket(session: Session, request: CreateSupportTicketInput) -> TicketResponse:
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
    return TicketResponse.model_validate(ticket)
