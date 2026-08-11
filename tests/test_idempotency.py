from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import (
    BusinessActionReceipt,
    Customer,
    Escalation,
    Order,
    RefundRequest,
    SupportTicket,
)
from app.models.entities import EscalationPriority, OrderStatus, RefundStatus
from app.resilience.errors import UnknownWriteOutcomeError
from app.services.idempotency import IdempotencyScope, commit_business_write
from app.tools.escalation import EscalateToHumanInput, escalate_to_human
from app.tools.orders import CancelOrderInput, cancel_order
from app.tools.refunds import RequestRefundInput, request_refund
from app.tools.tickets import CreateSupportTicketInput, create_support_ticket


def scope(key: str, actor_id: str = "idempotency-test-actor") -> IdempotencyScope:
    return IdempotencyScope(actor_id=actor_id, key=key)


def test_same_refund_request_returns_original_result(db_session: Session) -> None:
    request = RequestRefundInput(customer_id=1, order_id=2, reason="Damaged item")
    idempotency = scope("same-refund-request")

    first = request_refund(db_session, request, idempotency=idempotency)
    second = request_refund(db_session, request, idempotency=idempotency)

    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(RefundRequest)) == 1


def test_repeated_cancellation_with_different_requests_remains_safe(db_session: Session) -> None:
    request = CancelOrderInput(customer_id=1, order_id=3)

    first = cancel_order(db_session, request, idempotency=scope("cancel-request-one"))
    second = cancel_order(db_session, request, idempotency=scope("cancel-request-two"))

    assert first.changed is True
    assert second.changed is False
    assert db_session.scalar(select(func.count()).select_from(BusinessActionReceipt)) == 2


def test_duplicate_ticket_request_returns_one_ticket(db_session: Session) -> None:
    request = CreateSupportTicketInput(
        customer_id=1,
        order_id=3,
        category="delivery",
        description="Where is the delivery?",
    )
    idempotency = scope("same-ticket-request")

    first = create_support_ticket(db_session, request, idempotency=idempotency)
    second = create_support_ticket(db_session, request, idempotency=idempotency)

    assert second.id == first.id
    assert (
        db_session.scalar(
            select(func.count()).select_from(SupportTicket).where(SupportTicket.id > 2)
        )
        == 1
    )


def test_duplicate_escalation_request_returns_one_escalation(db_session: Session) -> None:
    request = EscalateToHumanInput(
        customer_id=1,
        ticket_id=1,
        order_id=1,
        reason="Operator needed",
        priority=EscalationPriority.HIGH,
        summary="Review this delivery issue",
    )
    idempotency = scope("same-escalation-request")

    first = escalate_to_human(db_session, request, idempotency=idempotency)
    second = escalate_to_human(db_session, request, idempotency=idempotency)

    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(Escalation)) == 1


def test_database_rejects_two_active_refunds_for_one_order(db_session: Session) -> None:
    db_session.add_all(
        [
            RefundRequest(
                customer_id=1,
                order_id=2,
                reason="First",
                status=RefundStatus.REQUESTED,
            ),
            RefundRequest(
                customer_id=1,
                order_id=2,
                reason="Second",
                status=RefundStatus.PROCESSING,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_direct_write_requires_request_idempotency_key(client: TestClient) -> None:
    response = client.post(
        "/tickets",
        json={"customer_id": 1, "category": "account", "description": "Please help"},
    )

    assert response.status_code == 422


def test_direct_api_replay_returns_original_business_effect(
    client: TestClient, db_session: Session
) -> None:
    request = {
        "customer_id": 1,
        "order_id": 3,
        "category": "delivery",
        "description": "Please check delivery",
    }
    headers = {"Idempotency-Key": "api-ticket-replay"}

    first = client.post("/tickets", json=request, headers=headers)
    second = client.post("/tickets", json=request, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert (
        db_session.scalar(
            select(func.count()).select_from(SupportTicket).where(SupportTicket.id > 2)
        )
        == 1
    )


def test_timeout_after_commit_reconciles_without_duplicate_replay(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = RequestRefundInput(customer_id=1, order_id=2, reason="Commit timeout")
    idempotency = scope("refund-commit-timeout")
    created = request_refund(db_session, request, idempotency=idempotency)
    real_commit = db_session.commit

    def commit_then_timeout() -> None:
        real_commit()
        raise TimeoutError("response lost after commit")

    monkeypatch.setattr(db_session, "commit", commit_then_timeout)
    with pytest.raises(UnknownWriteOutcomeError):
        commit_business_write(db_session, "request_refund")
    monkeypatch.setattr(db_session, "commit", real_commit)

    reconciled = request_refund(db_session, request, idempotency=idempotency)
    commit_business_write(db_session, "request_refund")

    assert reconciled.id == created.id
    assert db_session.scalar(select(func.count()).select_from(RefundRequest)) == 1


def test_concurrent_workers_share_one_refund_effect(tmp_path: Path) -> None:
    database_path = tmp_path / "idempotency.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with sessions.begin() as session:
        session.add(Customer(id=1, name="Concurrent", email="concurrent@example.com"))
        session.add(
            Order(
                id=1,
                customer_id=1,
                status=OrderStatus.DELIVERED,
                total_amount="25.00",
            )
        )

    def worker() -> int:
        with sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            result = request_refund(
                session,
                RequestRefundInput(customer_id=1, order_id=1, reason="Concurrent request"),
                idempotency=scope("concurrent-refund-request"),
            )
            commit_business_write(session, "request_refund")
            return result.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_ids = list(executor.map(lambda _: worker(), range(2)))

    with sessions() as session:
        assert len(set(result_ids)) == 1
        assert session.scalar(select(func.count()).select_from(RefundRequest)) == 1
        assert session.scalar(select(func.count()).select_from(BusinessActionReceipt)) == 1
