from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"


class EscalationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class EscalationStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="customer")
    refund_requests: Mapped[list["RefundRequest"]] = relationship(back_populates="customer")
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(String(20), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="orders")
    tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="order")
    refund_requests: Mapped[list["RefundRequest"]] = relationship(back_populates="order")
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="order")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="tickets")
    order: Mapped[Order | None] = relationship(back_populates="tickets")


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        Index(
            "uq_refund_requests_active_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'approved', 'processing')"),
            sqlite_where=text("status IN ('requested', 'approved', 'processing')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RefundStatus] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="refund_requests")
    order: Mapped[Order] = relationship(back_populates="refund_requests")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("support_tickets.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[EscalationPriority] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EscalationStatus] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="escalations")
    ticket: Mapped[SupportTicket | None] = relationship()
    order: Mapped[Order | None] = relationship(back_populates="escalations")


class BusinessActionReceipt(Base):
    __tablename__ = "business_action_receipts"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_business_action_receipt_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_id: Mapped[int] = mapped_column(index=True, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)


class PolicyAuditRecord(Base):
    """Durable operational policy evidence; never an authorization source."""

    __tablename__ = "policy_audit_events"
    __table_args__ = (
        Index("ix_policy_audit_conversation_created", "conversation_id", "created_at", "id"),
        Index("ix_policy_audit_customer_created", "effective_customer_id", "created_at", "id"),
        Index("ix_policy_audit_request_created", "request_id", "created_at", "id"),
        Index("ix_policy_audit_action_created", "action_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    agent_run_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    effective_customer_id: Mapped[int] = mapped_column(index=True, nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[int] = mapped_column(nullable=False)
    policy_outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    confirmation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revalidation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
