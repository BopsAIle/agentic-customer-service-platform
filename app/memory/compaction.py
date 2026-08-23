from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.memory.models import MemoryRecord
from app.memory.repository import MemoryRepository
from app.memory.schemas import MemoryStatus


def compact_customer_memory(
    session: Session,
    customer_id: int,
    now: datetime,
    repository: MemoryRepository | None = None,
    *,
    tenant_id: str = "default",
) -> int:
    repo = repository or MemoryRepository()
    active = repo.active_for_customer(session, customer_id, tenant_id)
    kept: dict[str, MemoryRecord] = {}
    compacted = 0
    for record in sorted(active, key=lambda item: (item.updated_at, item.id), reverse=True):
        if record.normalized_key in kept:
            repo.mark_status(record, MemoryStatus.SUPERSEDED, now)
            compacted += 1
        else:
            kept[record.normalized_key] = record
    if compacted:
        session.commit()
    return compacted
