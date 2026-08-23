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
from app.services.idempotency import IdempotencyScope
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
    execute: Callable[[Session, ExecutionContext, BaseModel, IdempotencyScope | None], object]


def _get_customer(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> CustomerResponse:
    del idempotency
    return get_customer(
        session, cast(GetCustomerInput, _scoped(context, request)), tenant_id=context.tenant_id
    )


def _get_customer_orders(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> list[OrderResponse]:
    del idempotency
    return get_customer_orders(
        session, cast(GetCustomerInput, _scoped(context, request)), tenant_id=context.tenant_id
    )


def _get_customer_tickets(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> list[TicketResponse]:
    del idempotency
    return get_customer_tickets(
        session, cast(GetCustomerInput, _scoped(context, request)), tenant_id=context.tenant_id
    )


def _get_order(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> OrderResponse:
    del idempotency
    return get_order(
        session, cast(GetOrderInput, _scoped(context, request)), tenant_id=context.tenant_id
    )


def _get_ticket(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> TicketResponse:
    del idempotency
    return get_ticket(
        session, cast(GetTicketInput, _scoped(context, request)), tenant_id=context.tenant_id
    )


def _create_ticket(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> TicketResponse:
    return create_support_ticket(
        session,
        cast(CreateSupportTicketInput, _scoped(context, request)),
        idempotency=_require_idempotency(idempotency),
        tenant_id=context.tenant_id,
    )


def _cancel_order(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> object:
    return cancel_order(
        session,
        cast(CancelOrderInput, _scoped(context, request)),
        idempotency=_require_idempotency(idempotency),
        tenant_id=context.tenant_id,
    )


def _request_refund(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> RefundRequestResponse:
    return request_refund(
        session,
        cast(RequestRefundInput, _scoped(context, request)),
        idempotency=_require_idempotency(idempotency),
        tenant_id=context.tenant_id,
    )


def _escalate_to_human(
    session: Session,
    context: ExecutionContext,
    request: BaseModel,
    idempotency: IdempotencyScope | None,
) -> EscalationResponse:
    return escalate_to_human(
        session,
        cast(EscalateToHumanInput, _scoped(context, request)),
        idempotency=_require_idempotency(idempotency),
        tenant_id=context.tenant_id,
    )


def _scoped(context: ExecutionContext, request: BaseModel) -> BaseModel:
    requested_customer = getattr(request, "customer_id", None)
    if requested_customer != context.effective_customer_id:
        resource_id = requested_customer if isinstance(requested_customer, int) else 0
        raise OwnershipError("Customer scope", resource_id, context.effective_customer_id)
    return request.model_copy(update={"customer_id": context.effective_customer_id})


def _require_idempotency(scope: IdempotencyScope | None) -> IdempotencyScope:
    if scope is None:
        raise ValueError("Business writes require an idempotency key.")
    return scope


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
