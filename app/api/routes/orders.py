from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error
from app.core.database import get_db
from app.schemas.domain import OrderResponse, RefundRequestResponse
from app.tools.base import ToolError
from app.tools.orders import (
    CancelOrderInput,
    CancelOrderOutput,
    GetOrderInput,
    cancel_order,
    get_order,
)
from app.tools.refunds import RequestRefundInput, request_refund

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderActionRequest(BaseModel):
    customer_id: int = Field(gt=0)


class RefundActionRequest(OrderActionRequest):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, session: Session = Depends(get_db)) -> OrderResponse:
    try:
        return get_order(session, GetOrderInput(order_id=order_id))
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.post("/{order_id}/cancel", response_model=CancelOrderOutput)
def cancel_order_by_id(
    order_id: int,
    request: OrderActionRequest,
    session: Session = Depends(get_db),
) -> CancelOrderOutput:
    try:
        result = cancel_order(
            session, CancelOrderInput(customer_id=request.customer_id, order_id=order_id)
        )
        session.commit()
        return result
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)


@router.post("/{order_id}/refunds", response_model=RefundRequestResponse, status_code=201)
def request_order_refund(
    order_id: int,
    request: RefundActionRequest,
    session: Session = Depends(get_db),
) -> RefundRequestResponse:
    try:
        result = request_refund(
            session,
            RequestRefundInput(
                customer_id=request.customer_id, order_id=order_id, reason=request.reason
            ),
        )
        session.commit()
        return result
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
