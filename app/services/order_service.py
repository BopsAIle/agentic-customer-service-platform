from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.get(Order, order_id)


def get_order_for_customer(session: Session, order_id: int, customer_id: int) -> Order | None:
    statement = select(Order).where(
        Order.id == order_id,
        Order.customer_id == customer_id,
    )
    return session.scalar(statement)
