from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SupportTicket


def get_ticket(
    session: Session, ticket_id: int, tenant_id: str = "default"
) -> SupportTicket | None:
    return session.scalar(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id
        )
    )


def get_ticket_for_customer(
    session: Session, ticket_id: int, customer_id: int, tenant_id: str = "default"
) -> SupportTicket | None:
    statement = select(SupportTicket).where(
        SupportTicket.id == ticket_id,
        SupportTicket.customer_id == customer_id,
        SupportTicket.tenant_id == tenant_id,
    )
    return session.scalar(statement)
