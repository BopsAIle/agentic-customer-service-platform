from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, SupportTicket


def get_customer(session: Session, customer_id: int, tenant_id: str = "default") -> Customer | None:
    return session.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )


def get_customer_for_scope(
    session: Session, customer_id: int, scope_customer_id: int, tenant_id: str = "default"
) -> Customer | None:
    statement = select(Customer).where(
        Customer.id == customer_id,
        Customer.id == scope_customer_id,
        Customer.tenant_id == tenant_id,
    )
    return session.scalar(statement)


def get_customer_orders(
    session: Session, customer_id: int, tenant_id: str = "default"
) -> list[Order]:
    statement = (
        select(Order)
        .where(Order.customer_id == customer_id, Order.tenant_id == tenant_id)
        .order_by(Order.id)
    )
    return list(session.scalars(statement))


def get_customer_tickets(
    session: Session, customer_id: int, tenant_id: str = "default"
) -> list[SupportTicket]:
    statement = (
        select(SupportTicket)
        .where(SupportTicket.customer_id == customer_id)
        .where(SupportTicket.tenant_id == tenant_id)
        .order_by(SupportTicket.id)
    )
    return list(session.scalars(statement))
