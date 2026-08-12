import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.core.config import Settings
from app.models import Order
from app.models.entities import OrderStatus, PolicyAuditRecord
from app.policies.models import PolicyAuditEvent, PolicyOutcome
from app.policies.repository import InMemoryPolicyAuditLog, SqlAlchemyPolicyAuditRepository


def audit_event(*, event_id: str, conversation_id: str = "conversation-a") -> PolicyAuditEvent:
    return PolicyAuditEvent(
        event_id=event_id,
        agent_run_id=f"run-{event_id}",
        request_id=f"request-{event_id}",
        conversation_id=conversation_id,
        actor_id="operator-audit-test",
        actor_type="support_operator",
        roles=["support_operator"],
        effective_customer_id=1,
        action_id="act_audit_test",
        tool_name="cancel_order",
        risk_level=2,
        policy_outcome=PolicyOutcome.REQUIRE_CONFIRMATION,
        reason_codes=["risk_2_confirmation_required"],
        timestamp=datetime.now(UTC),
    )


def test_durable_audit_append_query_is_bounded_and_deterministic(db_session: Session) -> None:
    repository = SqlAlchemyPolicyAuditRepository(db_session)
    first = audit_event(event_id="audit-first")
    second = audit_event(event_id="audit-second")
    repository.append(first)
    repository.append(second)

    other_instance = SqlAlchemyPolicyAuditRepository(db_session)
    events = other_instance.list_for_conversation("conversation-a", limit=1)

    assert [event.event_id for event in events] == ["audit-second"]
    assert other_instance.list_for_customer(999) == []


def test_durable_audit_event_identity_is_idempotent(db_session: Session) -> None:
    repository = SqlAlchemyPolicyAuditRepository(db_session)
    event = audit_event(event_id="audit-stable")

    repository.append(event)
    repository.append(event.model_copy(update={"reason_codes": ["replayed"]}))

    events = repository.list_for_agent_run(event.agent_run_id)
    assert len(events) == 1
    assert events[0].reason_codes == event.reason_codes


def test_in_memory_audit_adapter_is_bounded() -> None:
    repository = InMemoryPolicyAuditLog(max_events=2)
    for index in range(3):
        repository.append(audit_event(event_id=f"audit-{index}"))

    assert [event.event_id for event in repository.events] == ["audit-1", "audit-2"]


def test_concurrent_audit_appends_are_distinct_and_visible_to_other_instances(
    tmp_path: Path,
) -> None:
    database = tmp_path / "policy-audit.sqlite"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"timeout": 30},
        poolclass=NullPool,
    )
    cast(Any, PolicyAuditRecord.__table__).create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def append(index: int) -> None:
        with sessions() as session:
            SqlAlchemyPolicyAuditRepository(session).append(audit_event(event_id=f"audit-{index}"))

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(append, range(12)))

    with sessions() as session:
        events = SqlAlchemyPolicyAuditRepository(session).list_for_conversation(
            "conversation-a", limit=100
        )
    assert [event.event_id for event in events] == [f"audit-{index}" for index in range(12)]
    engine.dispose()


def test_production_and_integration_reject_memory_audit_backend() -> None:
    static_tokens = SecretStr(
        json.dumps(
            {
                "opaque-token": {
                    "actor_id": "operator",
                    "actor_type": "support_operator",
                    "roles": ["support_operator"],
                }
            }
        )
    )
    with pytest.raises(ValueError, match="policy audit"):
        Settings(
            app_env="production",
            auth_mode="static",
            auth_tokens_json=static_tokens,
            policy_audit_backend="memory",
        )
    with pytest.raises(ValueError, match="policy audit"):
        Settings(
            app_env="integration",
            auth_mode="local_demo",
            local_demo_auth_token=SecretStr("integration-token"),
            policy_audit_backend="memory",
        )


def test_policy_audit_serialization_contains_only_safe_structured_metadata() -> None:
    sentinel = "PRIVATE_PROMPT_MEMORY_CREDENTIAL_SENTINEL"
    event = audit_event(event_id="audit-safe").model_copy(
        update={"reason_codes": ["safe_reason_code"]}
    )
    serialized = json.dumps(event.model_dump(mode="json"), sort_keys=True)

    assert sentinel not in serialized
    assert "content" not in serialized
    assert "prompt" not in serialized


def test_audit_insert_failure_fails_before_business_mutation(db_session: Session) -> None:
    class FailingRepository:
        def append(self, event: PolicyAuditEvent) -> None:
            del event
            raise RuntimeError("audit storage unavailable")

        def list_for_agent_run(
            self, agent_run_id: str, *, limit: int = 50
        ) -> list[PolicyAuditEvent]:
            del agent_run_id, limit
            return []

        def list_for_conversation(
            self, conversation_id: str, *, limit: int = 50
        ) -> list[PolicyAuditEvent]:
            del conversation_id, limit
            return []

        def list_for_customer(self, customer_id: int, *, limit: int = 50) -> list[PolicyAuditEvent]:
            del customer_id, limit
            return []

    decision = StructuredDecision(
        intent=Intent.ORDER_CANCEL,
        request_type=AgentRequestType.WRITE_ACTION,
        tool_name="cancel_order",
        arguments={"customer_id": 1, "order_id": 3},
        reason="audit failure test",
    )
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([decision]),
        audit_log=FailingRepository(),
    )

    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        runtime.run(
            conversation_id="audit-failure",
            customer_id=1,
            message="Cancel order 3",
            session=db_session,
        )

    order = db_session.get(Order, 3)
    assert order is not None and order.status == OrderStatus.PENDING
