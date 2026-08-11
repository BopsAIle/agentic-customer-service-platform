from sqlalchemy.orm import Session

from app.models import SupportTicket


def get_ticket(session: Session, ticket_id: int) -> SupportTicket | None:
    return session.get(SupportTicket, ticket_id)
