import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.models import BusinessActionReceipt, Escalation, SupportTicket
from app.policies.confirmation import Clock
from app.policies.models import PolicyAuditEvent
from app.policies.repository import InMemoryPolicyAuditLog
from app.resilience.errors import UnknownWriteOutcomeError
from app.services.idempotency import IdempotencyScope, commit_business_write
from app.tools.tickets import CreateSupportTicketInput, create_support_ticket


def _decision(tool_name: str, arguments: dict[str, object]) -> StructuredDecision:
    return StructuredDecision(
        intent=(
            Intent.TICKET_CREATE
            if tool_name == "create_support_ticket"
            else Intent.HUMAN_ESCALATION
        ),
        request_type=(
            AgentRequestType.WRITE_ACTION
            if tool_name == "create_support_ticket"
            else AgentRequestType.ESCALATION
        ),
        tool_name=tool_name,
        arguments=arguments,
        reason="audit lifecycle test",
    )


def _ticket_arguments(description: str, *, order_id: int | None = 3) -> dict[str, object]:
    return {
        "customer_id": 1,
        "order_id": order_id,
        "category": "delivery",
        "description": description,
    }


def _execution_statuses(log: InMemoryPolicyAuditLog) -> list[str]:
    return [
        event.execution_status
        for event in log.events
        if event.stage == "execution" and event.execution_status is not None
    ]


def test_risk_one_write_has_policy_attempt_and_success_audit(
    db_session: Session,
) -> None:
    log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("create_support_ticket", _ticket_arguments("safe audit test"))]
        ),
        audit_log=log,
    )

    result = runtime.run(
        conversation_id="risk-one-audit",
        customer_id=1,
        message="Create a ticket.",
        session=db_session,
    )

    assert result.tool_call is not None and result.tool_call.status == "executed"
    assert [event.stage for event in log.events] == [
        "policy_evaluation",
        "execution",
        "execution",
    ]
    assert _execution_statuses(log) == ["attempted", "success"]
    assert log.events[0].policy_outcome.value == "allow"
    assert log.events[1].event_id != log.events[2].event_id
    assert log.events[1].action_id == log.events[2].action_id == log.events[0].action_id


def test_risk_one_write_failure_has_durable_failure_outcome(db_session: Session) -> None:
    log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("create_support_ticket", _ticket_arguments("bad order", order_id=999))]
        ),
        audit_log=log,
    )

    result = runtime.run(
        conversation_id="risk-one-failure-audit",
        customer_id=1,
        message="Create a ticket.",
        session=db_session,
    )

    assert result.error_category == "resource_not_found"
    assert _execution_statuses(log) == ["attempted", "failure"]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SupportTicket)
            .where(SupportTicket.description == "bad order")
        )
        == 0
    )


def test_risk_three_escalation_has_policy_and_execution_outcome(db_session: Session) -> None:
    log = InMemoryPolicyAuditLog()
    arguments = {
        "customer_id": 1,
        "ticket_id": 1,
        "reason": "operator requested",
        "priority": "high",
        "summary": "Escalation audit test",
    }
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision("escalate_to_human", arguments)]),
        audit_log=log,
    )

    result = runtime.run(
        conversation_id="risk-three-audit",
        customer_id=1,
        message="I need a human.",
        session=db_session,
    )

    assert result.tool_call is not None and result.tool_call.status == "executed"
    assert log.events[0].policy_outcome.value == "require_human"
    assert _execution_statuses(log) == ["attempted", "success"]
    assert db_session.scalar(select(Escalation)) is not None


def test_risk_two_execution_audit_is_not_duplicated_and_survives_resume(
    db_session: Session,
) -> None:
    log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("cancel_order", {"customer_id": 1, "order_id": 3})]
        ),
        audit_log=log,
    )

    pending = runtime.run(
        conversation_id="risk-two-audit",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    completed = runtime.run(
        conversation_id="risk-two-audit",
        customer_id=1,
        message="yes",
        session=db_session,
    )

    assert pending.pending_action is not None
    assert completed.agent_run_id == pending.agent_run_id
    assert [event.stage for event in log.events] == [
        "policy_evaluation",
        "confirmation",
        "policy_revalidation",
        "execution",
        "execution",
    ]
    assert _execution_statuses(log) == ["attempted", "success"]
    assert len({event.event_id for event in log.events}) == len(log.events)


class _TestClock(Clock):
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.mark.parametrize("confirmation", ["no", "expired"])
def test_risk_two_rejection_or_expiry_has_no_execution_success(
    db_session: Session, confirmation: str
) -> None:
    log = InMemoryPolicyAuditLog()
    clock = _TestClock()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("cancel_order", {"customer_id": 1, "order_id": 3})]
        ),
        audit_log=log,
        clock=clock,
        confirmation_ttl_seconds=300,
    )
    runtime.run(
        conversation_id=f"risk-two-{confirmation}",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    if confirmation == "expired":
        clock.advance(301)
        message = "yes"
    else:
        message = "no"
    result = runtime.run(
        conversation_id=f"risk-two-{confirmation}",
        customer_id=1,
        message=message,
        session=db_session,
    )

    assert result.pending_action is not None
    assert result.pending_action.status.value in {"rejected", "expired"}
    assert "success" not in _execution_statuses(log)
    assert "attempted" not in _execution_statuses(log)


def test_risk_three_escalation_failure_has_durable_failure_evidence(
    db_session: Session,
) -> None:
    log = InMemoryPolicyAuditLog()
    arguments = {
        "customer_id": 1,
        "ticket_id": 999,
        "reason": "operator requested",
        "priority": "high",
        "summary": "Escalation should fail safely",
    }
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision("escalate_to_human", arguments)]),
        audit_log=log,
    )

    result = runtime.run(
        conversation_id="risk-three-failure-audit",
        customer_id=1,
        message="I need a human.",
        session=db_session,
    )

    assert result.error_category == "resource_not_found"
    assert _execution_statuses(log) == ["attempted", "failure"]
    assert db_session.scalar(select(func.count()).select_from(Escalation)) == 0


class _FailingAuditLog(InMemoryPolicyAuditLog):
    def __init__(self, predicate: Callable[[PolicyAuditEvent], bool]) -> None:
        super().__init__()
        self.predicate = predicate

    def append(self, event: PolicyAuditEvent) -> None:
        if self.predicate(event):
            raise RuntimeError("audit storage unavailable")
        super().append(event)


def test_execution_audit_failure_before_write_fails_closed(db_session: Session) -> None:
    log = _FailingAuditLog(
        lambda event: event.stage == "execution" and event.execution_status == "attempted"
    )
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("create_support_ticket", _ticket_arguments("must not persist"))]
        ),
        audit_log=log,
    )

    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        runtime.run(
            conversation_id="audit-before-write",
            customer_id=1,
            message="Create a ticket.",
            session=db_session,
        )

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SupportTicket)
            .where(SupportTicket.description == "must not persist")
        )
        == 0
    )


def test_execution_audit_failure_after_commit_does_not_replay_write(
    db_session: Session,
) -> None:
    log = _FailingAuditLog(
        lambda event: event.stage == "execution" and event.execution_status == "success"
    )
    arguments = _ticket_arguments("committed-before-audit-failure")
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision("create_support_ticket", arguments)]),
        audit_log=log,
    )

    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        runtime.run(
            conversation_id="audit-after-write",
            customer_id=1,
            message="Create a ticket.",
            session=db_session,
        )

    tickets = list(
        db_session.scalars(
            select(SupportTicket).where(
                SupportTicket.description == "committed-before-audit-failure"
            )
        )
    )
    assert len(tickets) == 1
    assert db_session.scalar(select(func.count()).select_from(BusinessActionReceipt)) == 1

    # Reconciliation through the original idempotency identity loads the committed result;
    # it does not create a second ticket merely because success evidence was unavailable.
    action_id = next(event.action_id for event in log.events if event.stage == "policy_evaluation")
    context = ExecutionContext(
        request_id="reconcile-request",
        conversation_id="audit-after-write",
        principal=Principal(
            actor_id="legacy-runtime",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )
    reconciled = create_support_ticket(
        db_session,
        CreateSupportTicketInput.model_validate(arguments),
        idempotency=IdempotencyScope(actor_id=context.principal.actor_id, key=action_id or ""),
    )
    commit_business_write(db_session, "create_support_ticket")
    assert reconciled.id == tickets[0].id
    assert db_session.scalar(select(func.count()).select_from(SupportTicket)) == 3


def test_unknown_write_outcome_is_distinct_in_audit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = InMemoryPolicyAuditLog()

    def unknown_commit(session: Session, operation: str) -> None:
        del session
        raise UnknownWriteOutcomeError(operation)

    monkeypatch.setattr("app.agent.nodes.execute_tool.commit_business_write", unknown_commit)
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("create_support_ticket", _ticket_arguments("unknown outcome"))]
        ),
        audit_log=log,
    )

    result = runtime.run(
        conversation_id="unknown-write-audit",
        customer_id=1,
        message="Create a ticket.",
        session=db_session,
    )

    assert result.write_outcome_unknown is True
    assert _execution_statuses(log) == ["attempted", "unknown"]


def test_execution_audit_contains_no_raw_write_payloads(db_session: Session) -> None:
    sentinel = "SUPPORT_TICKET_PRIVATE_SENTINEL_13"
    log = InMemoryPolicyAuditLog()
    runtime = AgentRuntime(
        provider=FakeDecisionProvider(
            [_decision("create_support_ticket", _ticket_arguments(sentinel))]
        ),
        audit_log=log,
    )
    runtime.run(
        conversation_id="audit-privacy",
        customer_id=1,
        message="Create a ticket.",
        session=db_session,
    )

    serialized = json.dumps([event.model_dump(mode="json") for event in log.events])
    assert sentinel not in serialized
    assert "tool_arguments" not in serialized
