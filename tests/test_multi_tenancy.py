from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.memory.models import MemoryRecord
from app.memory.repository import MemoryRepository
from app.memory.schemas import MemorySource, MemoryStatus, MemoryType
from app.models import Customer, Tenant, TenantStatus
from app.persistence.checkpoint import checkpoint_thread_id
from app.policies.confirmation import belongs_to_context
from app.policies.models import PendingAction, PendingActionStatus, PolicyAuditEvent, PolicyOutcome
from app.policies.repository import InMemoryPolicyAuditLog
from app.services.customer_service import get_customer
from app.ui.demo import demo_scenarios
from app.ui.repository import InMemoryAgentRunProjectionRepository


def _principal(tenant_id: str, *, customer_id: int | None = None) -> Principal:
    return Principal(
        actor_id=f"operator-{tenant_id}",
        actor_type=ActorType.CUSTOMER if customer_id is not None else ActorType.SUPPORT_OPERATOR,
        roles=["customer"] if customer_id is not None else ["support_operator"],
        tenant_id=tenant_id,
        customer_id=customer_id,
    )


def _audit_event(tenant_id: str, event_id: str) -> PolicyAuditEvent:
    return PolicyAuditEvent(
        event_id=event_id,
        agent_run_id=f"run-{event_id}",
        request_id=f"request-{event_id}",
        conversation_id="conversation-shared",
        tenant_id=tenant_id,
        actor_id="operator",
        actor_type=ActorType.SUPPORT_OPERATOR,
        roles=["support_operator"],
        effective_customer_id=1,
        action_id=None,
        tool_name="order_list",
        risk_level=0,
        policy_outcome=PolicyOutcome.ALLOW,
        reason_codes=[],
        timestamp=datetime.now(UTC),
    )


def test_customer_queries_are_tenant_scoped(db_session: Session) -> None:
    db_session.add_all(
        [
            Tenant(id="tenant-a", name="Tenant A", status=TenantStatus.ACTIVE),
            Tenant(id="tenant-b", name="Tenant B", status=TenantStatus.ACTIVE),
            Customer(id=101, tenant_id="tenant-a", name="A", email="a@example.test"),
            Customer(id=102, tenant_id="tenant-b", name="B", email="b@example.test"),
        ]
    )
    db_session.commit()

    assert get_customer(db_session, 101, tenant_id="tenant-a") is not None
    assert get_customer(db_session, 101, tenant_id="tenant-b") is None
    assert get_customer(db_session, 102, tenant_id="tenant-a") is None


def test_memory_retrieval_cannot_cross_tenant_scope(db_session: Session) -> None:
    db_session.add_all(
        [
            Tenant(id="tenant-memory-a", name="A", status=TenantStatus.ACTIVE),
            Tenant(id="tenant-memory-b", name="B", status=TenantStatus.ACTIVE),
            MemoryRecord(
                tenant_id="tenant-memory-b",
                customer_id=1,
                memory_type=MemoryType.PREFERENCE,
                content="bounded preference",
                normalized_key="preference",
                source=MemorySource.USER_EXPLICIT,
                status=MemoryStatus.ACTIVE,
            ),
        ]
    )
    db_session.commit()

    repository = MemoryRepository()
    assert repository.active_for_customer(db_session, 1, tenant_id="tenant-memory-a") == []
    assert len(repository.active_for_customer(db_session, 1, tenant_id="tenant-memory-b")) == 1


def test_memory_repository_rejects_missing_tenant_context(db_session: Session) -> None:
    with pytest.raises(ValueError, match="tenant context"):
        MemoryRepository().active_for_customer(db_session, 1, tenant_id=None)  # type: ignore[arg-type]


def test_audit_and_projection_reads_are_tenant_scoped() -> None:
    audit = InMemoryPolicyAuditLog()
    audit.append(_audit_event("tenant-a", "event-a"))
    audit.append(_audit_event("tenant-b", "event-b"))
    assert [
        event.event_id
        for event in audit.list_for_conversation("conversation-shared", tenant_id="tenant-a")
    ] == ["event-a"]

    projections = InMemoryAgentRunProjectionRepository()
    scenario_a = demo_scenarios()[0].run.model_copy(
        update={"run_id": "run-a", "tenant_id": "tenant-a"}
    )
    scenario_b = demo_scenarios()[0].run.model_copy(
        update={"run_id": "run-b", "tenant_id": "tenant-b"}
    )
    projections.upsert(scenario_a)
    projections.upsert(scenario_b)
    assert projections.get_by_run_id("run-a", tenant_id="tenant-b") is None
    assert [run.run_id for run in projections.list_recent(tenant_id="tenant-a")] == ["run-a"]


def test_execution_context_derives_and_enforces_tenant() -> None:
    principal = _principal("tenant-context")
    context = ExecutionContext(
        request_id="request",
        conversation_id="conversation",
        principal=principal,
        effective_customer_id=1,
    )
    assert context.tenant_id == "tenant-context"

    with pytest.raises(ValueError, match="tenant scope"):
        ExecutionContext(
            request_id="request",
            conversation_id="conversation",
            principal=principal,
            tenant_id="other-tenant",
            effective_customer_id=1,
        )


def test_pending_confirmation_cannot_cross_tenant_context() -> None:
    context = ExecutionContext(
        request_id="request",
        conversation_id="conversation",
        principal=_principal("tenant-b"),
        effective_customer_id=1,
    )
    action = PendingAction(
        action_id="action",
        conversation_id="conversation",
        tenant_id="tenant-a",
        actor_id=context.principal.actor_id,
        actor_type=context.principal.actor_type,
        effective_customer_id=1,
        tool_name="request_refund",
        arguments={"customer_id": 1, "order_id": 1, "reason": "damaged"},
        risk_level=2,
        created_at=datetime.now(UTC),
        status=PendingActionStatus.PENDING,
    )
    assert not belongs_to_context(action, context)


def test_checkpoint_identity_changes_with_tenant_but_not_default_compatibility() -> None:
    base = dict(
        request_id="request",
        conversation_id="conversation",
        effective_customer_id=1,
    )
    tenant_a = ExecutionContext(principal=_principal("tenant-a"), **base)
    tenant_b = ExecutionContext(principal=_principal("tenant-b"), **base)
    assert checkpoint_thread_id(tenant_a) != checkpoint_thread_id(tenant_b)
    assert "tenant-tenant-a" in checkpoint_thread_id(tenant_a)


def test_tenant_model_has_explicit_lifecycle_fields() -> None:
    tenant = Tenant(id="tenant", name="Tenant", status=TenantStatus.ACTIVE)
    assert tenant.id == "tenant"
    assert tenant.status == TenantStatus.ACTIVE
    assert tenant.name == "Tenant"
