from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.context import ExecutionContext
from app.schemas.domain import (
    CustomerResponse,
    EscalationResponse,
    OrderResponse,
    RefundRequestResponse,
    TicketResponse,
)
from app.tools import registry
from app.tools.base import OwnershipError
from app.tools.customers import (
    GetCustomerInput,
    get_customer,
    get_customer_orders,
    get_customer_tickets,
)
from app.tools.escalation import EscalateToHumanInput, escalate_to_human
from app.tools.orders import CancelOrderInput, GetOrderInput, cancel_order, get_order
from app.tools.refunds import RequestRefundInput, request_refund
from app.tools.tickets import (
    CreateSupportTicketInput,
    GetTicketInput,
    create_support_ticket,
    get_ticket,
)


@dataclass(frozen=True, slots=True)
class AgentToolDefinition:
    input_model: type[BaseModel]
    execute: Callable[[Session, ExecutionContext, BaseModel], object]


def _get_customer(
    session: Session, context: ExecutionContext, request: BaseModel
) -> CustomerResponse:
    return get_customer(session, cast(GetCustomerInput, _scoped(context, request)))


def _get_customer_orders(
    session: Session, context: ExecutionContext, request: BaseModel
) -> list[OrderResponse]:
    return get_customer_orders(session, cast(GetCustomerInput, _scoped(context, request)))


def _get_customer_tickets(
    session: Session, context: ExecutionContext, request: BaseModel
) -> list[TicketResponse]:
    return get_customer_tickets(session, cast(GetCustomerInput, _scoped(context, request)))


def _get_order(session: Session, context: ExecutionContext, request: BaseModel) -> OrderResponse:
    return get_order(session, cast(GetOrderInput, _scoped(context, request)))


def _get_ticket(session: Session, context: ExecutionContext, request: BaseModel) -> TicketResponse:
    return get_ticket(session, cast(GetTicketInput, _scoped(context, request)))


def _create_ticket(
    session: Session, context: ExecutionContext, request: BaseModel
) -> TicketResponse:
    return create_support_ticket(session, cast(CreateSupportTicketInput, _scoped(context, request)))


def _cancel_order(session: Session, context: ExecutionContext, request: BaseModel) -> object:
    return cancel_order(session, cast(CancelOrderInput, _scoped(context, request)))


def _request_refund(
    session: Session, context: ExecutionContext, request: BaseModel
) -> RefundRequestResponse:
    return request_refund(session, cast(RequestRefundInput, _scoped(context, request)))


def _escalate_to_human(
    session: Session, context: ExecutionContext, request: BaseModel
) -> EscalationResponse:
    return escalate_to_human(session, cast(EscalateToHumanInput, _scoped(context, request)))


def _scoped(context: ExecutionContext, request: BaseModel) -> BaseModel:
    requested_customer = getattr(request, "customer_id", None)
    if requested_customer != context.effective_customer_id:
        resource_id = requested_customer if isinstance(requested_customer, int) else 0
        raise OwnershipError("Customer scope", resource_id, context.effective_customer_id)
    return request.model_copy(update={"customer_id": context.effective_customer_id})


TOOL_DEFINITIONS: dict[str, AgentToolDefinition] = {
    "get_customer": AgentToolDefinition(GetCustomerInput, _get_customer),
    "get_customer_orders": AgentToolDefinition(GetCustomerInput, _get_customer_orders),
    "get_order": AgentToolDefinition(GetOrderInput, _get_order),
    "get_customer_tickets": AgentToolDefinition(GetCustomerInput, _get_customer_tickets),
    "get_ticket": AgentToolDefinition(GetTicketInput, _get_ticket),
    "create_support_ticket": AgentToolDefinition(CreateSupportTicketInput, _create_ticket),
    "cancel_order": AgentToolDefinition(CancelOrderInput, _cancel_order),
    "request_refund": AgentToolDefinition(RequestRefundInput, _request_refund),
    "escalate_to_human": AgentToolDefinition(EscalateToHumanInput, _escalate_to_human),
}


def get_agent_tool_definition(name: str) -> AgentToolDefinition | None:
    if name not in registry.TOOL_REGISTRY:
        return None
    return TOOL_DEFINITIONS.get(name)
