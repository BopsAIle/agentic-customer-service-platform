from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import require_support_operator
from app.core.config import get_settings
from app.core.database import get_db
from app.memory.service import MemoryService
from app.policies.repository import SqlAlchemyPolicyAuditRepository
from app.ui.repository import AgentRunProjectionRepository, build_agent_run_projection_repository
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


def _run_or_404(run_id: str, repository: AgentRunProjectionRepository) -> AgentRunView:
    run = repository.get_by_run_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return run


@router.get("/agent-runs", response_model=list[AgentRunView])
def agent_runs(
    customer_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_db),
) -> list[AgentRunView]:
    repository = build_agent_run_projection_repository(get_settings(), session)
    if customer_id is not None:
        return repository.list_for_customer(customer_id, limit=limit)
    return repository.list_recent(limit=limit)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationView,
    response_model_exclude_none=True,
)
def conversation(conversation_id: str, session: Session = Depends(get_db)) -> ConversationView:
    repository = build_agent_run_projection_repository(get_settings(), session)
    runs = repository.list_for_conversation(
        conversation_id, limit=get_settings().agent_run_projection_query_limit
    )
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
def agent_run(agent_run_id: str, session: Session = Depends(get_db)) -> AgentRunView:
    return _run_or_404(agent_run_id, build_agent_run_projection_repository(get_settings(), session))


@router.get("/tool-events/{agent_run_id}", response_model=list[UIToolEvent])
def tool_events(agent_run_id: str, session: Session = Depends(get_db)) -> list[UIToolEvent]:
    return _run_or_404(
        agent_run_id, build_agent_run_projection_repository(get_settings(), session)
    ).tools


@router.get("/policy-events/{agent_run_id}", response_model=list[UIPolicyEvent])
def policy_events(agent_run_id: str, session: Session = Depends(get_db)) -> list[UIPolicyEvent]:
    events = SqlAlchemyPolicyAuditRepository(session).list_for_agent_run(
        agent_run_id, limit=get_settings().policy_audit_query_limit
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy audit not found")
    return [_policy_event_view(event) for event in events]


@router.get("/policy-audit/{conversation_id}", response_model=list[UIPolicyEvent])
def policy_audit(conversation_id: str, session: Session = Depends(get_db)) -> list[UIPolicyEvent]:
    events = SqlAlchemyPolicyAuditRepository(session).list_for_conversation(
        conversation_id, limit=get_settings().policy_audit_query_limit
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy audit not found")
    return [_policy_event_view(event) for event in events]


def _policy_event_view(event: object) -> UIPolicyEvent:
    from app.policies.models import PolicyAuditEvent

    if not isinstance(event, PolicyAuditEvent):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid audit event"
        )
    return UIPolicyEvent(
        event_id=event.event_id,
        request_id=event.request_id,
        conversation_id=event.conversation_id,
        timestamp=event.timestamp,
        stage=event.stage,
        confirmation_status=event.confirmation_status,
        revalidation=event.revalidation,
        execution_status=event.execution_status,
        actor_id=event.actor_id,
        actor_type=event.actor_type.value,
        roles=list(event.roles),
        effective_customer_id=event.effective_customer_id,
        tool_name=event.tool_name,
        risk_level=event.risk_level,
        outcome=event.policy_outcome.value,
        reason_codes=event.reason_codes[:10],
    )


@router.get("/rag-events/{agent_run_id}", response_model=list[UIRagDocument])
def rag_events(agent_run_id: str, session: Session = Depends(get_db)) -> list[UIRagDocument]:
    return _run_or_404(
        agent_run_id, build_agent_run_projection_repository(get_settings(), session)
    ).rag_documents


@router.get("/traces/{agent_run_id}", response_model=list[UITraceEvent])
def traces(agent_run_id: str, session: Session = Depends(get_db)) -> list[UITraceEvent]:
    return _run_or_404(
        agent_run_id, build_agent_run_projection_repository(get_settings(), session)
    ).trace


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
