from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_principal, resolve_customer_scope
from app.auth.models import Principal
from app.core.config import get_settings
from app.core.database import get_db
from app.memory.models import MemoryRecord
from app.memory.schemas import MemoryRecordView
from app.memory.service import MemoryService

router = APIRouter(prefix="/customers", tags=["memories"])


def get_memory_service() -> MemoryService:
    settings = get_settings()
    return MemoryService(
        enabled=settings.memory_enabled,
        max_context_items=settings.memory_max_context_items,
        default_ttl_days=settings.memory_default_ttl_days,
        support_context_ttl_days=settings.memory_support_context_ttl_days,
    )


@router.get("/{customer_id}/memories", response_model=list[MemoryRecordView])
def list_memories(
    customer_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemoryRecordView]:
    if customer_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid customer ID")
    customer_scope = resolve_customer_scope(principal, customer_id)
    return service.retrieve(
        session,
        customer_scope.customer_id,
        "",
        principal=customer_scope.principal,
    )


@router.delete("/{customer_id}/memories/{memory_id}")
def delete_memory(
    customer_id: int,
    memory_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    service: MemoryService = Depends(get_memory_service),
) -> dict[str, str]:
    if customer_id <= 0 or memory_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid memory ID")
    customer_scope = resolve_customer_scope(principal, customer_id)
    record = session.get(MemoryRecord, memory_id)
    if (
        record is None
        or record.customer_id != customer_scope.customer_id
        or record.tenant_id != (customer_scope.principal.tenant_id or "default")
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    result = service.forget(
        session,
        customer_scope.customer_id,
        record.normalized_key,
        tenant_id=customer_scope.principal.tenant_id or "default",
    )
    return {"status": result.status}
