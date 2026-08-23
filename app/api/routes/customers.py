from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import raise_http_for_tool_error
from app.auth.dependencies import get_current_principal, resolve_customer_scope
from app.auth.models import Principal
from app.core.database import get_db
from app.schemas.domain import CustomerResponse, OrderResponse, TicketResponse
from app.tools.base import ToolError
from app.tools.customers import GetCustomerInput
from app.tools.customers import get_customer as get_customer_tool
from app.tools.customers import get_customer_orders as get_customer_orders_tool
from app.tools.customers import get_customer_tickets as get_customer_tickets_tool

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> CustomerResponse:
    customer_scope = resolve_customer_scope(principal, customer_id)
    try:
        return get_customer_tool(
            session,
            GetCustomerInput(customer_id=customer_scope.customer_id),
            tenant_id=principal.tenant_id or "default",
        )
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.get("/{customer_id}/orders", response_model=list[OrderResponse])
def get_customer_orders(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> list[OrderResponse]:
    customer_scope = resolve_customer_scope(principal, customer_id)
    try:
        return get_customer_orders_tool(
            session,
            GetCustomerInput(customer_id=customer_scope.customer_id),
            tenant_id=principal.tenant_id or "default",
        )
    except ToolError as error:
        raise_http_for_tool_error(error)


@router.get("/{customer_id}/tickets", response_model=list[TicketResponse])
def get_customer_tickets(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> list[TicketResponse]:
    customer_scope = resolve_customer_scope(principal, customer_id)
    try:
        return get_customer_tickets_tool(
            session,
            GetCustomerInput(customer_id=customer_scope.customer_id),
            tenant_id=principal.tenant_id or "default",
        )
    except ToolError as error:
        raise_http_for_tool_error(error)
