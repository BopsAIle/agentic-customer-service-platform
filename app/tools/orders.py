from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus
from app.schemas.domain import OrderResponse
from app.services.order_service import get_order as get_order_record
from app.services.order_service import get_order_for_customer
from app.tools.base import (
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
)


class GetOrderInput(BaseModel):
    order_id: int = Field(gt=0)
    customer_id: int = Field(gt=0)


class CancelOrderInput(BaseModel):
    customer_id: int = Field(gt=0)
    order_id: int = Field(gt=0)


class CancelOrderOutput(BaseModel):
    order_id: int
    customer_id: int
    status: OrderStatus
    changed: bool
    message: str


def get_order(session: Session, request: GetOrderInput) -> OrderResponse:
    order = get_order_for_customer(session, request.order_id, request.customer_id)
    if order is None:
        raise ResourceNotFoundError("Order", request.order_id)
    return OrderResponse.model_validate(order)


def cancel_order(session: Session, request: CancelOrderInput) -> CancelOrderOutput:
    order = validate_cancel_order(session, request)
    order_status = OrderStatus(order.status)
    if order_status == OrderStatus.CANCELLED:
        return CancelOrderOutput(
            order_id=order.id,
            customer_id=order.customer_id,
            status=order.status,
            changed=False,
            message="Order was already cancelled",
        )
    order.status = OrderStatus.CANCELLED
    session.flush()
    return CancelOrderOutput(
        order_id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        changed=True,
        message="Order cancelled",
    )


def validate_cancel_order(session: Session, request: CancelOrderInput) -> Order:
    order = get_order_record(session, request.order_id)
    if order is None:
        raise ResourceNotFoundError("Order", request.order_id)
    if order.customer_id != request.customer_id:
        raise OwnershipError("Order", request.order_id, request.customer_id)
    order_status = OrderStatus(order.status)
    if order_status not in {
        OrderStatus.PENDING,
        OrderStatus.PROCESSING,
        OrderStatus.CANCELLED,
    }:
        raise InvalidStateTransitionError(
            f"Order {order.id} cannot be cancelled from status {order_status.value}"
        )
    return order
