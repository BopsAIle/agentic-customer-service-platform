from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.models import MemoryRecord
from app.memory.schemas import MemoryStatus


class MemoryRepository:
    def active_for_customer(self, session: Session, customer_id: int) -> list[MemoryRecord]:
        return list(
            session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.customer_id == customer_id)
                .where(MemoryRecord.status == MemoryStatus.ACTIVE)
                .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.id.desc())
            )
        )

    def active_by_key(
        self, session: Session, customer_id: int, normalized_key: str
    ) -> list[MemoryRecord]:
        return list(
            session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.customer_id == customer_id)
                .where(MemoryRecord.normalized_key == normalized_key)
                .where(MemoryRecord.status == MemoryStatus.ACTIVE)
            )
        )

    def mark_status(self, record: MemoryRecord, status: MemoryStatus, now: datetime) -> None:
        record.status = status
        record.updated_at = now
