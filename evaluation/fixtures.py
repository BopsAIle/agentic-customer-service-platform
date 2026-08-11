from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Customer, Order, SupportTicket
from app.models.entities import OrderStatus, TicketStatus


def evaluation_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with factory.begin() as session:
        session.add_all(
            [
                Customer(id=1, name="Ada Lovelace", email="ada@example.com"),
                Customer(id=2, name="Grace Hopper", email="grace@example.com"),
                Customer(id=3, name="Alan Turing", email="alan@example.com"),
            ]
        )
        session.add_all(
            [
                Order(
                    id=1,
                    customer_id=1,
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("149.99"),
                ),
                Order(
                    id=2, customer_id=1, status=OrderStatus.SHIPPED, total_amount=Decimal("39.50")
                ),
                Order(
                    id=3,
                    customer_id=1,
                    status=OrderStatus.PROCESSING,
                    total_amount=Decimal("89.00"),
                ),
                Order(
                    id=4,
                    customer_id=2,
                    status=OrderStatus.CANCELLED,
                    total_amount=Decimal("210.00"),
                ),
                Order(
                    id=5, customer_id=3, status=OrderStatus.PENDING, total_amount=Decimal("24.75")
                ),
                Order(
                    id=6,
                    customer_id=3,
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("560.00"),
                ),
            ]
        )
        session.add_all(
            [
                SupportTicket(
                    id=1,
                    customer_id=1,
                    order_id=1,
                    category="delivery",
                    status=TicketStatus.RESOLVED,
                    description="Package arrived late.",
                ),
                SupportTicket(
                    id=2,
                    customer_id=2,
                    order_id=3,
                    category="billing",
                    status=TicketStatus.OPEN,
                    description="Explain the charge.",
                ),
                SupportTicket(
                    id=3,
                    customer_id=2,
                    category="account",
                    status=TicketStatus.IN_PROGRESS,
                    description="Update my contact details.",
                ),
                SupportTicket(
                    id=4,
                    customer_id=3,
                    order_id=6,
                    category="product",
                    status=TicketStatus.CLOSED,
                    description="Product information.",
                ),
            ]
        )
    return factory()
