from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.models import MemoryRecord
from app.memory.schemas import MemoryStatus
from app.observability.metrics import record_tenant_scope


class MemoryRepository:
    def active_for_customer(
        self, session: Session, customer_id: int, tenant_id: str = "default"
    ) -> list[MemoryRecord]:
        _require_tenant(tenant_id)
        return list(
            session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.customer_id == customer_id)
                .where(MemoryRecord.tenant_id == tenant_id)
                .where(MemoryRecord.status == MemoryStatus.ACTIVE)
                .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.id.desc())
            )
        )

    def active_by_key(
        self, session: Session, customer_id: int, normalized_key: str, tenant_id: str = "default"
    ) -> list[MemoryRecord]:
        _require_tenant(tenant_id)
        return list(
            session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.customer_id == customer_id)
                .where(MemoryRecord.tenant_id == tenant_id)
                .where(MemoryRecord.normalized_key == normalized_key)
                .where(MemoryRecord.status == MemoryStatus.ACTIVE)
            )
        )

    def mark_status(self, record: MemoryRecord, status: MemoryStatus, now: datetime) -> None:
        record.status = status
        record.updated_at = now


def _require_tenant(tenant_id: str | None) -> str:
    if tenant_id is None or not tenant_id.strip():
        record_tenant_scope(decision="rejected", status="missing_tenant_context")
        raise ValueError("tenant context is required for memory queries")
    record_tenant_scope(decision="accepted", status="tenant_scoped")
    return tenant_id
