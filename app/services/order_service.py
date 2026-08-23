from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order


def get_order(session: Session, order_id: int, tenant_id: str = "default") -> Order | None:
    return session.scalar(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))


def get_order_for_customer(
    session: Session, order_id: int, customer_id: int, tenant_id: str = "default"
) -> Order | None:
    statement = select(Order).where(
        Order.id == order_id,
        Order.customer_id == customer_id,
        Order.tenant_id == tenant_id,
    )
    return session.scalar(statement)
