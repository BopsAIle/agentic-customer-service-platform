from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.schemas.domain import CustomerResponse, OrderResponse, TicketResponse
from app.services import customer_service
from app.tools.base import ResourceNotFoundError


class GetCustomerInput(BaseModel):
    customer_id: int = Field(gt=0)


def get_customer(session: Session, request: GetCustomerInput) -> CustomerResponse:
    customer = customer_service.get_customer_for_scope(
        session, request.customer_id, request.customer_id
    )
    if customer is None:
        raise ResourceNotFoundError("Customer", request.customer_id)
    return CustomerResponse.model_validate(customer)


def get_customer_orders(session: Session, request: GetCustomerInput) -> list[OrderResponse]:
    customer = customer_service.get_customer(session, request.customer_id)
    if customer is None:
        raise ResourceNotFoundError("Customer", request.customer_id)
    return [
        OrderResponse.model_validate(order)
        for order in customer_service.get_customer_orders(session, request.customer_id)
    ]


def get_customer_tickets(session: Session, request: GetCustomerInput) -> list[TicketResponse]:
    customer = customer_service.get_customer(session, request.customer_id)
    if customer is None:
        raise ResourceNotFoundError("Customer", request.customer_id)
    return [
        TicketResponse.model_validate(ticket)
        for ticket in customer_service.get_customer_tickets(session, request.customer_id)
    ]
