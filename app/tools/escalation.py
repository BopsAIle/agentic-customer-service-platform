from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    Escalation,
    EscalationPriority,
    EscalationStatus,
    Order,
    SupportTicket,
)
from app.schemas.domain import EscalationResponse
from app.tools.base import OwnershipError, ResourceNotFoundError


class EscalateToHumanInput(BaseModel):
    customer_id: int = Field(gt=0)
    ticket_id: int | None = Field(default=None, gt=0)
    order_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    priority: EscalationPriority
    summary: str = Field(min_length=1, max_length=5000)


def escalate_to_human(session: Session, request: EscalateToHumanInput) -> EscalationResponse:
    if session.get(Customer, request.customer_id) is None:
        raise ResourceNotFoundError("Customer", request.customer_id)
    if request.ticket_id is not None:
        ticket = session.get(SupportTicket, request.ticket_id)
        if ticket is None:
            raise ResourceNotFoundError("Support ticket", request.ticket_id)
        if ticket.customer_id != request.customer_id:
            raise OwnershipError("Support ticket", request.ticket_id, request.customer_id)
    if request.order_id is not None:
        order = session.get(Order, request.order_id)
        if order is None:
            raise ResourceNotFoundError("Order", request.order_id)
        if order.customer_id != request.customer_id:
            raise OwnershipError("Order", request.order_id, request.customer_id)
    escalation = Escalation(
        customer_id=request.customer_id,
        ticket_id=request.ticket_id,
        order_id=request.order_id,
        reason=request.reason,
        priority=request.priority,
        summary=request.summary,
        status=EscalationStatus.QUEUED,
    )
    session.add(escalation)
    session.flush()
    return EscalationResponse.model_validate(escalation)
