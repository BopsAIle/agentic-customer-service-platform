from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, RefundRequest, RefundStatus
from app.schemas.domain import RefundRequestResponse
from app.tools.base import (
    DuplicateActionError,
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
)


class RequestRefundInput(BaseModel):
    customer_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


def request_refund(session: Session, request: RequestRefundInput) -> RefundRequestResponse:
    validate_refund_request(session, request)
    refund = RefundRequest(
        customer_id=request.customer_id,
        order_id=request.order_id,
        reason=request.reason,
        status=RefundStatus.REQUESTED,
    )
    session.add(refund)
    session.flush()
    return RefundRequestResponse.model_validate(refund)


def validate_refund_request(session: Session, request: RequestRefundInput) -> None:
    order = session.get(Order, request.order_id)
    if order is None:
        raise ResourceNotFoundError("Order", request.order_id)
    if order.customer_id != request.customer_id:
        raise OwnershipError("Order", request.order_id, request.customer_id)
    order_status = OrderStatus(order.status)
    if order_status != OrderStatus.DELIVERED:
        raise InvalidStateTransitionError(
            f"Order {order.id} is not eligible for a refund from status {order_status.value}"
        )
    active_statuses = {
        RefundStatus.REQUESTED,
        RefundStatus.APPROVED,
        RefundStatus.PROCESSING,
    }
    existing = session.scalar(
        select(RefundRequest)
        .where(RefundRequest.order_id == request.order_id)
        .where(RefundRequest.status.in_(active_statuses))
    )
    if existing is not None:
        raise DuplicateActionError(f"An active refund request already exists for order {order.id}")
