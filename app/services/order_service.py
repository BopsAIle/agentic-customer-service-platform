from sqlalchemy.orm import Session

from app.models import Order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.get(Order, order_id)
