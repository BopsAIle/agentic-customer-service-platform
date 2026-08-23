from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
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
from app.schemas.domain import OrderResponse, RefundRequestResponse
from app.services.idempotency import IdempotencyScope, commit_business_write
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
def get_order_by_id(
    order_id: int,
    customer_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> OrderResponse:
    customer_scope = resolve_customer_scope(principal, customer_id)
    try:
        return get_order(
            session,
            GetOrderInput(order_id=order_id, customer_id=customer_scope.customer_id),
            tenant_id=principal.tenant_id or "default",
        )
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.post("/{order_id}/cancel", response_model=CancelOrderOutput)
def cancel_order_by_id(
    order_id: int,
    request: OrderActionRequest,
    idempotency_key: str = Depends(get_idempotency_key),
    principal: Principal = Depends(require_support_operator),
    session: Session = Depends(get_db),
) -> CancelOrderOutput:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        result = cancel_order(
            session,
            CancelOrderInput(customer_id=customer_scope.customer_id, order_id=order_id),
            idempotency=IdempotencyScope(
                actor_id=principal.actor_id,
                key=idempotency_key,
                tenant_id=principal.tenant_id or "default",
            ),
            tenant_id=principal.tenant_id or "default",
        )
        commit_business_write(session, "cancel_order")
        return result
    except UnknownWriteOutcomeError as error:
        raise_http_for_unknown_write(error)
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)


@router.post("/{order_id}/refunds", response_model=RefundRequestResponse, status_code=201)
def request_order_refund(
    order_id: int,
    request: RefundActionRequest,
    idempotency_key: str = Depends(get_idempotency_key),
    principal: Principal = Depends(require_support_operator),
    session: Session = Depends(get_db),
) -> RefundRequestResponse:
    customer_scope = resolve_customer_scope(principal, request.customer_id)
    try:
        result = request_refund(
            session,
            RequestRefundInput(
                customer_id=customer_scope.customer_id,
                order_id=order_id,
                reason=request.reason,
            ),
            idempotency=IdempotencyScope(
                actor_id=principal.actor_id,
                key=idempotency_key,
                tenant_id=principal.tenant_id or "default",
            ),
            tenant_id=principal.tenant_id or "default",
        )
        commit_business_write(session, "request_refund")
        return result
    except UnknownWriteOutcomeError as error:
        raise_http_for_unknown_write(error)
    except ToolError as error:
        session.rollback()
        raise_http_for_tool_error(error)
