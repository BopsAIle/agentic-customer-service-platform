from datetime import datetime
from typing import Protocol

from app.policies.models import PendingAction, PendingActionStatus


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


def parse_confirmation(message: str) -> str:
    normalized = " ".join(message.casefold().strip().split())
    if normalized in {"yes", "confirm", "confirmed", "proceed", "do it", "yes, proceed"}:
        return "confirmed"
    if normalized in {"no", "cancel", "never mind", "don't do it", "do not do it"}:
        return "rejected"
    return "ambiguous"


def is_expired(action: PendingAction, now: datetime, ttl_seconds: int) -> bool:
    return (now - action.created_at).total_seconds() >= ttl_seconds


def transition(action: PendingAction, status: PendingActionStatus) -> PendingAction:
    return action.model_copy(update={"status": status})
