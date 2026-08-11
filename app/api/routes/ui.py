from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import require_support_operator
from app.core.config import get_settings
from app.core.database import get_db
from app.memory.service import MemoryService
from app.ui.projection import get_projection_store
from app.ui.schemas import (
    AgentRunView,
    ConversationView,
    MemoryView,
    SystemComponentHealth,
    SystemHealthView,
    UIPolicyEvent,
    UIRagDocument,
    UIToolEvent,
    UITraceEvent,
)

router = APIRouter(
    prefix="/ui",
    tags=["operator-console"],
    dependencies=[Depends(require_support_operator)],
)


def _run_or_404(run_id: str) -> AgentRunView:
    run = get_projection_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return run


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationView,
    response_model_exclude_none=True,
)
def conversation(conversation_id: str) -> ConversationView:
    runs = get_projection_store().conversation(conversation_id)
    if not runs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    messages = [
        {"role": "user", "content_available": False},
        {"role": "assistant", "content_available": False},
    ] * len(runs)
    return ConversationView(
        conversation_id=conversation_id,
        customer_id=runs[-1].customer_id,
        run_count=len(runs),
        runs=runs,
        messages=messages,
    )


@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunView)
def agent_run(agent_run_id: str) -> AgentRunView:
    return _run_or_404(agent_run_id)


@router.get("/tool-events/{agent_run_id}", response_model=list[UIToolEvent])
def tool_events(agent_run_id: str) -> list[UIToolEvent]:
    return _run_or_404(agent_run_id).tools


@router.get("/policy-events/{agent_run_id}", response_model=list[UIPolicyEvent])
def policy_events(agent_run_id: str) -> list[UIPolicyEvent]:
    return _run_or_404(agent_run_id).policy


@router.get("/rag-events/{agent_run_id}", response_model=list[UIRagDocument])
def rag_events(agent_run_id: str) -> list[UIRagDocument]:
    return _run_or_404(agent_run_id).rag_documents


@router.get("/traces/{agent_run_id}", response_model=list[UITraceEvent])
def traces(agent_run_id: str) -> list[UITraceEvent]:
    return _run_or_404(agent_run_id).trace


@router.get("/memory/{customer_id}", response_model=list[MemoryView])
def memory(customer_id: int, session: Session = Depends(get_db)) -> list[MemoryView]:
    if customer_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid customer ID")
    settings = get_settings()
    service = MemoryService(
        enabled=settings.memory_enabled,
        max_context_items=20,
        default_ttl_days=settings.memory_default_ttl_days,
        support_context_ttl_days=settings.memory_support_context_ttl_days,
    )
    records = service.retrieve(session, customer_id, "")
    return [
        MemoryView(
            id=record.id,
            customer_id=record.customer_id,
            memory_type=str(getattr(record.memory_type, "value", record.memory_type)),
            normalized_key=record.normalized_key,
            source=str(getattr(record.source, "value", record.source)),
            status=str(getattr(record.status, "value", record.status)),
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
        )
        for record in records
    ]


@router.get("/system-health", response_model=SystemHealthView)
def system_health(session: Session = Depends(get_db)) -> SystemHealthView:
    components: list[SystemComponentHealth] = []
    try:
        session.execute(text("SELECT 1"))
        components.append(
            SystemComponentHealth(name="database", status="healthy", detail="reachable")
        )
    except Exception:
        components.append(
            SystemComponentHealth(name="database", status="degraded", detail="unavailable")
        )
    settings = get_settings()
    components.extend(
        [
            SystemComponentHealth(
                name="llm", status="configured", detail="provider boundary available"
            ),
            SystemComponentHealth(
                name="retriever",
                status="healthy",
                detail="local retrieval boundary available",
            ),
            SystemComponentHealth(
                name="memory",
                status="healthy" if settings.memory_enabled else "disabled",
                detail="persistent memory configuration",
            ),
        ]
    )
    overall = (
        "healthy"
        if all(item.status in {"healthy", "configured", "disabled"} for item in components)
        else "degraded"
    )
    return SystemHealthView(status=overall, components=components)
