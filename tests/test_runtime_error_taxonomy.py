import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.agent.errors import (
    RuntimeFailureSource,
    classify_runtime_error,
)
from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import (
    AgentErrorCategory,
    AgentRequestType,
    AgentResponse,
    Intent,
    StructuredDecision,
)
from app.agent.tool_catalog import TOOL_DEFINITIONS, AgentToolDefinition
from app.models import SupportTicket
from app.policies.models import PolicyAuditEvent
from app.policies.repository import DEFAULT_AUDIT_QUERY_LIMIT, InMemoryPolicyAuditLog
from app.resilience.errors import FailureCategory, UnknownWriteOutcomeError
from app.services.idempotency import IdempotencyScope
from app.tools.base import ToolError

SENTINEL = "RUNTIME_TAXONOMY_PRIVATE_SENTINEL_14"


def _ticket_decision() -> StructuredDecision:
    return StructuredDecision(
        intent=Intent.TICKET_CREATE,
        request_type=AgentRequestType.WRITE_ACTION,
        tool_name="create_support_ticket",
        arguments={
            "customer_id": 1,
            "order_id": 3,
            "category": "delivery",
            "description": SENTINEL,
        },
        reason="taxonomy test",
    )


def _install_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: Callable[[], BaseException],
) -> None:
    original = TOOL_DEFINITIONS["create_support_ticket"]

    def execute(
        session: Session,
        context: Any,
        request: Any,
        idempotency: IdempotencyScope | None,
    ) -> object:
        del session, context, request, idempotency
        raise failure()

    monkeypatch.setitem(
        TOOL_DEFINITIONS,
        "create_support_ticket",
        AgentToolDefinition(original.input_model, execute),
    )


def _run_ticket(
    db_session: Session,
    *,
    audit_log: InMemoryPolicyAuditLog | None = None,
) -> AgentResponse:
    return AgentRuntime(
        provider=FakeDecisionProvider([_ticket_decision()]),
        audit_log=audit_log,
    ).run(
        conversation_id="taxonomy-ticket",
        customer_id=1,
        message="Create a support ticket.",
        session=db_session,
    )


def test_classifier_keeps_small_source_aware_taxonomy() -> None:
    assert (
        classify_runtime_error(RuntimeError(SENTINEL), source=RuntimeFailureSource.TOOL).category
        == AgentErrorCategory.INTERNAL_ERROR
    )
    assert (
        classify_runtime_error(ToolError(SENTINEL), source=RuntimeFailureSource.TOOL).category
        == AgentErrorCategory.TOOL_ERROR
    )
    assert (
        classify_runtime_error(
            RuntimeError(SENTINEL), source=RuntimeFailureSource.DEPENDENCY
        ).category
        == AgentErrorCategory.DEPENDENCY_ERROR
    )
    assert (
        classify_runtime_error(RuntimeError(SENTINEL), source=RuntimeFailureSource.LLM).category
        == AgentErrorCategory.LLM_ERROR
    )
    assert (
        classify_runtime_error(RuntimeError(SENTINEL), source=RuntimeFailureSource.POLICY).category
        == AgentErrorCategory.INTERNAL_ERROR
    )


def test_memory_source_distinguishes_dependency_and_internal_failures() -> None:
    assert (
        classify_runtime_error(
            OperationalError("write", {}, RuntimeError(SENTINEL)),
            source=RuntimeFailureSource.MEMORY,
        ).category
        == AgentErrorCategory.DEPENDENCY_ERROR
    )
    assert (
        classify_runtime_error(RuntimeError(SENTINEL), source=RuntimeFailureSource.MEMORY).category
        == AgentErrorCategory.INTERNAL_ERROR
    )


def test_genuine_llm_provider_failure_remains_llm_error(db_session: Session) -> None:
    class UnavailableProvider:
        def decide(self, **kwargs: object) -> StructuredDecision:
            del kwargs
            raise ConnectionError(SENTINEL)

    result = AgentRuntime(provider=UnavailableProvider()).run(
        conversation_id="taxonomy-llm",
        customer_id=1,
        message="Help me.",
        session=db_session,
    )

    assert result.error_category == AgentErrorCategory.LLM_ERROR
    assert result.failure_category == "llm_unavailable"
    assert SENTINEL not in result.message


def test_malformed_llm_output_remains_llm_error(db_session: Session) -> None:
    class MalformedProvider:
        def decide(self, **kwargs: object) -> StructuredDecision:
            del kwargs
            raise ValueError(SENTINEL)

    result = AgentRuntime(provider=MalformedProvider()).run(
        conversation_id="taxonomy-malformed",
        customer_id=1,
        message="Help me.",
        session=db_session,
    )

    assert result.error_category == AgentErrorCategory.LLM_ERROR
    assert result.failure_category == "llm_malformed_output"
    assert SENTINEL not in result.message


def test_controlled_tool_failure_is_tool_error_and_audited(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_tool_failure(monkeypatch, lambda: ToolError(SENTINEL))
    audit_log = InMemoryPolicyAuditLog()

    result = _run_ticket(db_session, audit_log=audit_log)

    assert result.error_category == AgentErrorCategory.TOOL_ERROR
    assert db_session.query(SupportTicket).filter_by(description=SENTINEL).count() == 0
    execution = [event for event in audit_log.events if event.stage == "execution"]
    assert execution[-1].execution_status == "failure"
    assert AgentErrorCategory.TOOL_ERROR.value in execution[-1].reason_codes
    assert SENTINEL not in json.dumps([event.model_dump(mode="json") for event in audit_log.events])


def test_database_dependency_failure_is_not_tool_or_llm_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_tool_failure(
        monkeypatch,
        lambda: OperationalError("select", {}, RuntimeError(SENTINEL)),
    )
    result = _run_ticket(db_session)

    assert result.error_category == AgentErrorCategory.DEPENDENCY_ERROR
    assert result.failure_category == "database_unavailable"
    assert SENTINEL not in result.message


def test_unexpected_tool_runtime_failure_is_internal_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_tool_failure(monkeypatch, lambda: RuntimeError(SENTINEL))
    result = _run_ticket(db_session)

    assert result.error_category == AgentErrorCategory.INTERNAL_ERROR
    assert result.failure_category == "internal_error"
    assert SENTINEL not in result.message


def test_unknown_write_outcome_keeps_distinct_reconciliation_semantics(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_tool_failure(
        monkeypatch,
        lambda: UnknownWriteOutcomeError("create_support_ticket"),
    )
    result = _run_ticket(db_session)

    assert result.error_category == AgentErrorCategory.UNKNOWN_WRITE_OUTCOME
    assert result.write_outcome_unknown is True
    assert result.failure_category == FailureCategory.TOOL_TIMEOUT.value


def test_timeout_keeps_detailed_tool_timeout_reason(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_tool_failure(monkeypatch, lambda: TimeoutError(SENTINEL))
    result = _run_ticket(db_session)

    assert result.error_category == AgentErrorCategory.DEPENDENCY_ERROR
    assert result.failure_category == FailureCategory.TOOL_TIMEOUT.value
    assert SENTINEL not in result.message


def test_policy_deny_is_not_runtime_error(db_session: Session) -> None:
    from app.policies.engine import PolicyEngine
    from app.policies.models import PolicyDecision, PolicyOutcome

    class DenyingPolicy(PolicyEngine):
        def evaluate(self, **kwargs: object) -> PolicyDecision:
            del kwargs
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                tool_name="create_support_ticket",
                risk_level=1,
                reasons=["test_denied"],
            )

    result = AgentRuntime(
        provider=FakeDecisionProvider([_ticket_decision()]),
        policy_engine=DenyingPolicy(),
    ).run(
        conversation_id="taxonomy-policy-deny",
        customer_id=1,
        message="Create a ticket.",
        session=db_session,
    )

    assert result.error_category == AgentErrorCategory.POLICY_DENIED
    assert result.failure_category is None


def test_audit_failure_is_dependency_classified_and_fail_closed(db_session: Session) -> None:
    class FailingAudit:
        def append(self, event: PolicyAuditEvent) -> None:
            del event
            raise RuntimeError(SENTINEL)

        def list_for_agent_run(
            self,
            agent_run_id: str,
            *,
            tenant_id: str = "default",
            limit: int = DEFAULT_AUDIT_QUERY_LIMIT,
        ) -> list[PolicyAuditEvent]:
            del agent_run_id, tenant_id, limit
            return []

        def list_for_conversation(
            self,
            conversation_id: str,
            *,
            tenant_id: str = "default",
            limit: int = DEFAULT_AUDIT_QUERY_LIMIT,
        ) -> list[PolicyAuditEvent]:
            del conversation_id, tenant_id, limit
            return []

        def list_for_customer(
            self,
            customer_id: int,
            *,
            tenant_id: str = "default",
            limit: int = DEFAULT_AUDIT_QUERY_LIMIT,
        ) -> list[PolicyAuditEvent]:
            del customer_id, tenant_id, limit
            return []

    with pytest.raises(Exception) as raised:
        AgentRuntime(
            provider=FakeDecisionProvider([_ticket_decision()]),
            audit_log=FailingAudit(),
        ).run(
            conversation_id="taxonomy-audit",
            customer_id=1,
            message="Create a ticket.",
            session=db_session,
        )

    classification = classify_runtime_error(raised.value, source=RuntimeFailureSource.AUDIT)
    assert classification.category == AgentErrorCategory.DEPENDENCY_ERROR
    assert SENTINEL not in str(raised.value)
    assert db_session.query(SupportTicket).filter_by(description=SENTINEL).count() == 0


def test_projection_failure_is_observational_dependency_and_does_not_leak(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingProjection:
        def upsert(self, projection: object) -> None:
            del projection
            raise RuntimeError(SENTINEL)

    caplog.set_level(logging.WARNING, logger="app.agent.runtime")
    result = AgentRuntime(
        provider=FakeDecisionProvider(
            [
                StructuredDecision(
                    intent=Intent.CAPABILITY_QUESTION,
                    request_type=AgentRequestType.INFORMATIONAL,
                    reason="projection taxonomy test",
                )
            ]
        ),
        projection_repository=FailingProjection(),  # type: ignore[arg-type]
    ).run(
        conversation_id="taxonomy-projection",
        customer_id=1,
        message="What can you do?",
        session=db_session,
    )

    assert result.error_category is None
    assert any(
        record.__dict__.get("error_category") == AgentErrorCategory.DEPENDENCY_ERROR.value
        for record in caplog.records
    )
    assert all(SENTINEL not in record.getMessage() for record in caplog.records)
