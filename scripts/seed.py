from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.models import Customer, Escalation, Order, RefundRequest, SupportTicket
from app.models.entities import OrderStatus, TicketStatus


def seed() -> None:
    with SessionLocal.begin() as session:
        session.execute(delete(Escalation))
        session.execute(delete(RefundRequest))
        session.execute(delete(SupportTicket))
        session.execute(delete(Order))
        session.execute(delete(Customer))
        customers = [
            Customer(
                id=1,
                name="Ada Lovelace",
                email="ada@example.com",
                created_at=datetime(2026, 1, 1),
            ),
            Customer(
                id=2,
                name="Grace Hopper",
                email="grace@example.com",
                created_at=datetime(2026, 1, 2),
            ),
            Customer(
                id=3,
                name="Alan Turing",
                email="alan@example.com",
                created_at=datetime(2026, 1, 3),
            ),
        ]
        session.add_all(customers)
        session.add_all(
            [
                Order(
                    id=1,
                    customer_id=1,
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("149.99"),
                    created_at=datetime(2026, 1, 10),
                ),
                Order(
                    id=2,
                    customer_id=1,
                    status=OrderStatus.SHIPPED,
                    total_amount=Decimal("39.50"),
                    created_at=datetime(2026, 1, 11),
                ),
                Order(
                    id=3,
                    customer_id=2,
                    status=OrderStatus.PROCESSING,
                    total_amount=Decimal("89.00"),
                    created_at=datetime(2026, 1, 12),
                ),
                Order(
                    id=4,
                    customer_id=2,
                    status=OrderStatus.CANCELLED,
                    total_amount=Decimal("210.00"),
                    created_at=datetime(2026, 1, 13),
                ),
                Order(
                    id=5,
                    customer_id=3,
                    status=OrderStatus.PENDING,
                    total_amount=Decimal("24.75"),
                    created_at=datetime(2026, 1, 14),
                ),
                Order(
                    id=6,
                    customer_id=3,
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("560.00"),
                    created_at=datetime(2026, 1, 15),
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
                    description="Package arrived later than expected.",
                    created_at=datetime(2026, 1, 16),
                ),
                SupportTicket(
                    id=2,
                    customer_id=2,
                    order_id=3,
                    category="billing",
                    status=TicketStatus.OPEN,
                    description="Please explain the charge on my order.",
                    created_at=datetime(2026, 1, 17),
                ),
                SupportTicket(
                    id=3,
                    customer_id=2,
                    order_id=None,
                    category="account",
                    status=TicketStatus.IN_PROGRESS,
                    description="I need to update my contact details.",
                    created_at=datetime(2026, 1, 18),
                ),
                SupportTicket(
                    id=4,
                    customer_id=3,
                    order_id=6,
                    category="product",
                    status=TicketStatus.CLOSED,
                    description="The product information was helpful.",
                    created_at=datetime(2026, 1, 19),
                ),
            ]
        )


if __name__ == "__main__":
    seed()
