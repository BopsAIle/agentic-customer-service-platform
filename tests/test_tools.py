import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Escalation, EscalationPriority, RefundRequest
from app.models.entities import OrderStatus, RefundStatus
from app.services.idempotency import IdempotencyScope
from app.tools.base import (
    DuplicateActionError,
    InvalidStateTransitionError,
    OwnershipError,
    ResourceNotFoundError,
)
from app.tools.customers import GetCustomerInput, get_customer, get_customer_orders
from app.tools.escalation import EscalateToHumanInput, escalate_to_human
from app.tools.orders import CancelOrderInput, cancel_order
from app.tools.refunds import RequestRefundInput, request_refund
from app.tools.registry import get_tool, list_tools
from app.tools.tickets import CreateSupportTicketInput, create_support_ticket


def idempotency(key: str) -> IdempotencyScope:
    return IdempotencyScope(actor_id="tool-test-actor", key=key)


def test_successful_customer_and_order_reads(db_session: Session) -> None:
    customer = get_customer(db_session, GetCustomerInput(customer_id=1))
    orders = get_customer_orders(db_session, GetCustomerInput(customer_id=1))
    assert customer.email == "test@example.com"
    assert [order.id for order in orders] == [1, 2, 3, 4]


def test_tool_registry_exposes_explicit_catalog() -> None:
    names = [metadata.name for metadata in list_tools()]
    assert names == [
        "get_customer",
        "get_customer_orders",
        "get_order",
        "get_customer_tickets",
        "get_ticket",
        "create_support_ticket",
        "cancel_order",
        "request_refund",
        "escalate_to_human",
    ]
    assert get_tool("cancel_order").risk_level == 2


def test_read_missing_resource(client: TestClient) -> None:
    response = client.get("/orders/999", params={"customer_id": 1})
    assert response.status_code == 404


def test_create_ticket_and_validate_order_ownership(db_session: Session) -> None:
    result = create_support_ticket(
        db_session,
        CreateSupportTicketInput(
            customer_id=1,
            order_id=3,
            category="delivery",
            description="Please check the delivery date.",
        ),
        idempotency=idempotency("ticket-create-one"),
    )
    assert result.status == "open"
    with pytest.raises(OwnershipError):
        create_support_ticket(
            db_session,
            CreateSupportTicketInput(
                customer_id=2,
                order_id=3,
                category="delivery",
                description="This must fail.",
            ),
            idempotency=idempotency("ticket-wrong-owner"),
        )


def test_create_ticket_invalid_customer(client: TestClient) -> None:
    response = client.post(
        "/tickets",
        headers={"Idempotency-Key": "ticket-invalid-customer"},
        json={
            "customer_id": 999,
            "category": "account",
            "description": "This must fail.",
        },
    )
    assert response.status_code == 404


def test_cancel_pending_and_processing_orders(db_session: Session) -> None:
    pending = cancel_order(
        db_session,
        CancelOrderInput(customer_id=1, order_id=3),
        idempotency=idempotency("cancel-pending-order"),
    )
    processing = cancel_order(
        db_session,
        CancelOrderInput(customer_id=1, order_id=4),
        idempotency=idempotency("cancel-processing-order"),
    )
    assert pending.status == OrderStatus.CANCELLED
    assert processing.status == OrderStatus.CANCELLED
    assert pending.changed is True
    assert processing.changed is True


@pytest.mark.parametrize("order_id", [1, 2])
def test_cancel_rejects_shipped_and_delivered(db_session: Session, order_id: int) -> None:
    with pytest.raises(InvalidStateTransitionError):
        cancel_order(
            db_session,
            CancelOrderInput(customer_id=1, order_id=order_id),
            idempotency=idempotency(f"cancel-ineligible-{order_id}"),
        )


def test_cancel_is_idempotent(db_session: Session) -> None:
    scope = idempotency("cancel-repeat-order-3")
    first = cancel_order(db_session, CancelOrderInput(customer_id=1, order_id=3), idempotency=scope)
    second = cancel_order(
        db_session, CancelOrderInput(customer_id=1, order_id=3), idempotency=scope
    )
    assert first.changed is True
    assert second.changed is False
    assert second.status == OrderStatus.CANCELLED


def test_cancel_rejects_cross_customer_order(db_session: Session) -> None:
    with pytest.raises(OwnershipError):
        cancel_order(
            db_session,
            CancelOrderInput(customer_id=2, order_id=3),
            idempotency=idempotency("cancel-cross-customer"),
        )


def test_refund_delivered_order_and_duplicate_request(db_session: Session) -> None:
    result = request_refund(
        db_session,
        RequestRefundInput(customer_id=1, order_id=2, reason="Item arrived damaged."),
        idempotency=idempotency("refund-first-request"),
    )
    assert result.status == RefundStatus.REQUESTED
    with pytest.raises(DuplicateActionError):
        request_refund(
            db_session,
            RequestRefundInput(customer_id=1, order_id=2, reason="Second request."),
            idempotency=idempotency("refund-second-request"),
        )
    assert db_session.scalar(select(RefundRequest).where(RefundRequest.order_id == 2)) is not None


def test_refund_rejects_non_delivered_order(db_session: Session) -> None:
    with pytest.raises(InvalidStateTransitionError):
        request_refund(
            db_session,
            RequestRefundInput(customer_id=1, order_id=1, reason="Not eligible."),
            idempotency=idempotency("refund-ineligible-order"),
        )


def test_refund_rejects_cross_customer_order(db_session: Session) -> None:
    with pytest.raises(OwnershipError):
        request_refund(
            db_session,
            RequestRefundInput(customer_id=1, order_id=5, reason="Not mine."),
            idempotency=idempotency("refund-cross-customer"),
        )


def test_escalation_persists_and_validates_references(db_session: Session) -> None:
    result = escalate_to_human(
        db_session,
        EscalateToHumanInput(
            customer_id=1,
            ticket_id=1,
            order_id=1,
            reason="Customer needs an operator.",
            priority=EscalationPriority.HIGH,
            summary="Delivery issue needs review.",
        ),
        idempotency=idempotency("escalation-success"),
    )
    assert result.status == "queued"
    assert db_session.scalar(select(Escalation).where(Escalation.id == result.id)) is not None
    with pytest.raises(ResourceNotFoundError):
        escalate_to_human(
            db_session,
            EscalateToHumanInput(
                customer_id=1,
                ticket_id=999,
                reason="Missing ticket.",
                priority=EscalationPriority.LOW,
                summary="This must fail.",
            ),
            idempotency=idempotency("escalation-missing-ticket"),
        )
    with pytest.raises(OwnershipError):
        escalate_to_human(
            db_session,
            EscalateToHumanInput(
                customer_id=1,
                ticket_id=2,
                reason="Wrong customer.",
                priority=EscalationPriority.URGENT,
                summary="This must fail.",
            ),
            idempotency=idempotency("escalation-wrong-owner"),
        )
