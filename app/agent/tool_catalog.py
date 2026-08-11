from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.domain import (
    CustomerResponse,
    EscalationResponse,
    OrderResponse,
    RefundRequestResponse,
    TicketResponse,
)
from app.tools import registry
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
    execute: Callable[[Session, BaseModel], object]


def _get_customer(session: Session, request: BaseModel) -> CustomerResponse:
    return get_customer(session, cast(GetCustomerInput, request))


def _get_customer_orders(session: Session, request: BaseModel) -> list[OrderResponse]:
    return get_customer_orders(session, cast(GetCustomerInput, request))


def _get_customer_tickets(session: Session, request: BaseModel) -> list[TicketResponse]:
    return get_customer_tickets(session, cast(GetCustomerInput, request))


def _get_order(session: Session, request: BaseModel) -> OrderResponse:
    return get_order(session, cast(GetOrderInput, request))


def _get_ticket(session: Session, request: BaseModel) -> TicketResponse:
    return get_ticket(session, cast(GetTicketInput, request))


def _create_ticket(session: Session, request: BaseModel) -> TicketResponse:
    return create_support_ticket(session, cast(CreateSupportTicketInput, request))


def _cancel_order(session: Session, request: BaseModel) -> object:
    return cancel_order(session, cast(CancelOrderInput, request))


def _request_refund(session: Session, request: BaseModel) -> RefundRequestResponse:
    return request_refund(session, cast(RequestRefundInput, request))


def _escalate_to_human(session: Session, request: BaseModel) -> EscalationResponse:
    return escalate_to_human(session, cast(EscalateToHumanInput, request))


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
