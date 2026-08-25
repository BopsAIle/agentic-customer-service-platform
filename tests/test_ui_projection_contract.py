from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent.decision_compiler import CompiledDecision, CompileStatus
from app.agent.schemas import AgentErrorCategory, AgentRequestType, AgentResponse, Intent
from app.api.routes.ui import _bounded_operator_view
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.ui.projection import get_projection_store
from app.ui.repository import SqlAlchemyAgentRunProjectionRepository
from app.ui.schemas import AgentRunView, UIDecisionEvidence, UIRetrievalMetadata
from app.ui.trace import trace_event_key_for_node, trace_stage_for_node


def _context() -> ExecutionContext:
    return ExecutionContext(
        request_id="projection-contract-request",
        conversation_id="projection-contract-conversation",
        principal=Principal(
            actor_id="projection-contract-operator",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )


def test_trace_nodes_map_to_stable_operator_stage_ids() -> None:
    assert trace_stage_for_node("route_request") == "routing"
    assert trace_stage_for_node("policy_revalidate") == "policy_evaluation"
    assert trace_stage_for_node("escalate") == "execution_authority"
    assert trace_stage_for_node("retrieve_memory") == "memory_context"
    assert trace_stage_for_node("unknown_node") == "internal"
    assert trace_event_key_for_node("understand_request") == "proposal.generated"
    assert trace_event_key_for_node("evaluate_policy") == "policy.checked"


def test_projection_exposes_bounded_decision_evidence_without_provider_text() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="projection-contract-run",
        message="A refund reason is required.",
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.UNCLEAR,
        decision_reason="provider text must not be projected",
    )
    state: dict[str, Any] = {
        "compile_result": CompiledDecision(
            status=CompileStatus.CLARIFICATION_REQUIRED,
            intent=Intent.REFUND_REQUEST,
            request_type=AgentRequestType.UNCLEAR,
            reason="A refund reason is required.",
        ),
        "grounding_status": "grounded",
        "grounding_reference_type": "explicit_order",
        "grounding_trusted_source": "current_user_message",
        "target_validation_status": "admissible",
        "selected_tool": None,
        "tool_execution_status": None,
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "answer_grounding": {
            "status": "pass",
            "sources_used": 1,
            "citation_count": 1,
            "citation_coverage": 1.0,
            "unsupported_claim_count": 0,
            "confidence": 0.9,
            "accepted": True,
        },
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-contract",
    ) as projection:
        store.record_node("compile_decision", "ok", 1.0)
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.trace[0].stage == "grounding"
    assert view.evidence.grounding.status == "grounded"
    assert view.evidence.target_validation.status == "admissible"
    assert view.evidence.compiler.status == "clarification_required"
    assert view.evidence.compiler.reason == "A refund reason is required."
    assert view.decision_reason == "A refund reason is required."
    assert view.answer_grounding.status == "pass"
    assert view.answer_grounding.citation_coverage == 1.0
    assert "provider text" not in view.model_dump_json()


def test_projection_redacts_filesystem_paths_from_rag_metadata() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="rag-safe-source-run",
        message="Refund policy answer.",
        intent=Intent.REFUND_POLICY,
        request_type=AgentRequestType.KNOWLEDGE_ONLY,
    )
    state: dict[str, Any] = {
        "retrieved_chunks": [
            {
                "chunk_id": "refund-policy#eligibility",
                "title": "Refund Policy",
                "section": "Eligibility",
                "source": "/app/.venv/lib/python3.12/site-packages/app/knowledge/refund-policy.md",
                "score": 0.9,
            }
        ],
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-safe-source",
    ) as projection:
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.rag_documents[0].source == "Refund Policy"
    assert view.rag_documents[0].section == "Eligibility"
    assert "/" not in view.rag_documents[0].source
    assert "site-packages" not in view.model_dump_json()


def test_projection_excludes_forensic_policy_inputs_from_trace_metadata() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="forensic-policy-run",
        message="Your request is awaiting confirmation.",
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
    )
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-forensic-policy",
    ) as projection:
        store.record_node(
            "policy_revalidate",
            "ok",
            1.0,
            {
                "original_pending_policy_inputs": '{"customer_id":1}',
                "restored_policy_inputs_hash": "secret-hash",
                "policy_revalidation_result": "passed",
                "restored_fields_count": 4,
            },
        )
        view = store.build_view(
            projection,
            response=response,
            state={"memory_context": []},
            policy_events=[],
            duration_ms=1.0,
        )

    metadata = _bounded_operator_view(view).trace[0].metadata
    assert "original_pending_policy_inputs" not in metadata
    assert "restored_policy_inputs_hash" not in metadata
    assert metadata["policy_revalidation_result"] == "passed"
    assert metadata["restored_fields_count"] == 4


def test_projection_separates_business_validation_from_policy_and_tool_execution() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="business-validation-run",
        message="The order was not found.",
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        error_category=AgentErrorCategory.RESOURCE_NOT_FOUND,
    )
    state: dict[str, Any] = {
        "compile_result": None,
        "selected_tool": "request_refund",
        "tool_arguments": {"customer_id": 1, "order_id": 999, "reason": "damaged"},
        "tool_execution_status": "failed",
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-business-validation",
    ) as projection:
        store.record_node("execute_tool", "error", 1.0)
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.evidence.decision == "validation_failed"
    assert view.evidence.reason == "Referenced business resource was not found."
    assert view.evidence.validation_stage == "business_validation"
    assert view.evidence.execution_status == "failed"
    assert view.tools[0].status == "failed_during_execution"
    assert "Policy outcome" not in (view.decision_reason or "")


def test_projection_marks_unexecuted_tool_as_blocked_before_execution() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="policy-denial-run",
        message="The request did not pass verification.",
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        error_category=AgentErrorCategory.POLICY_DENIED,
    )
    state: dict[str, Any] = {
        "compile_result": None,
        "selected_tool": "request_refund",
        "tool_arguments": {"customer_id": 1, "order_id": 2, "reason": "damaged"},
        "tool_execution_status": None,
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-policy-denial",
    ) as projection:
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.evidence.decision == "deny"
    assert view.evidence.validation_stage == "policy_evaluation"
    assert view.tools[0].status == "blocked_before_execution"


def test_projection_labels_known_cross_customer_access_as_authorization_denial() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="cross-customer-run",
        message="I can't access that order.",
        intent=Intent.ORDER_LOOKUP,
        request_type=AgentRequestType.READ_ACTION,
        error_category=AgentErrorCategory.OWNERSHIP_VIOLATION,
    )
    state: dict[str, Any] = {
        "compile_result": None,
        "selected_tool": "get_order",
        "tool_execution_status": None,
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-cross-customer",
    ) as projection:
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.evidence.decision == "deny"
    assert view.evidence.reason == "cross_customer_access_attempt"
    assert view.evidence.validation_stage == "authorization"
    assert view.evidence.execution_status == "not_attempted"
    assert view.evidence.authority == "not_granted"


def test_projection_labels_confirmation_replay_without_new_execution() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="replay-run",
        message="That action was already completed; I did not execute it again.",
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
    )
    state: dict[str, Any] = {
        "compile_result": None,
        "selected_tool": None,
        "tool_execution_status": None,
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "replay_detected": True,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "memory_context": [],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-replay",
    ) as projection:
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.operation_type == "idempotency_replay"
    assert view.evidence.decision == "already_completed"
    assert view.evidence.reason == "idempotency_replay_prevented"
    assert view.evidence.validation_stage == "idempotency"
    assert view.evidence.execution_status == "not_repeated"


def test_memory_usage_is_bounded_and_annotates_memory_trace() -> None:
    store = get_projection_store()
    response = AgentResponse(
        conversation_id="projection-contract-conversation",
        agent_run_id="memory-influence-run",
        message="The request is ready for review.",
        intent=Intent.ORDER_LOOKUP,
        request_type=AgentRequestType.KNOWLEDGE_ONLY,
    )
    state: dict[str, Any] = {
        "compile_result": None,
        "grounding_status": "grounded",
        "grounding_reference_type": None,
        "grounding_trusted_source": None,
        "target_validation_status": "not_applicable",
        "selected_tool": None,
        "tool_execution_status": None,
        "pending_action": None,
        "policy_decision": None,
        "write_outcome_unknown": False,
        "retrieved_chunks": [],
        "retrieval_metadata": {},
        "memory_context": [
            {
                "normalized_key": "update_preference_email",
                "memory_type": "preference",
                "content": "private memory must not be projected",
            }
        ],
    }
    with store.capture(
        run_id=response.agent_run_id,
        context=_context(),
        trace_id="trace-memory-influence",
    ) as projection:
        store.record_node("retrieve_memory", "ok", 1.0)
        view = store.build_view(
            projection,
            response=response,
            state=state,  # type: ignore[arg-type]
            policy_events=[],
            duration_ms=1.0,
        )

    assert view.memory.retrieved is True
    assert view.memory.retrieved_count == 1
    assert view.memory.items_used == 1
    assert view.memory.purpose == "context_enrichment"
    assert view.memory.decision_influence == "context_only"
    assert view.memory.authority_influence == "none"
    assert view.trace[0].stage == "memory_context"
    assert view.trace[0].metadata == {"items_used": 1, "role": "context_enrichment"}
    assert "private memory must not be projected" not in view.model_dump_json()


def test_decision_evidence_round_trips_through_durable_projection(db_session: Session) -> None:
    view = AgentRunView(
        run_id="durable-evidence-run",
        request_id="durable-evidence-request",
        conversation_id="durable-evidence-conversation",
        customer_id=1,
        actor_id="operator",
        actor_type="support_operator",
        intent="refund_request",
        request_type="write_action",
        operation_type="memory_summary",
        status="waiting_confirmation",
        started_at=datetime.now(UTC),
        duration_ms=1.0,
        memory={
            "item_count": 1,
            "keys": ["update_preference_email"],
            "types": ["preference"],
            "retrieved": True,
            "retrieved_count": 1,
            "items_used": 1,
            "purpose": "context_enrichment",
            "decision_influence": "context_only",
            "authority_influence": "none",
        },
        retrieval_metadata=UIRetrievalMetadata(),
        decision_reason="Policy outcome: require_confirmation.",
        evidence=UIDecisionEvidence(
            grounding={"status": "grounded"},
            target_validation={"status": "admissible"},
            confirmation={"status": "pending", "required": True, "risk_level": 2},
            write_outcome={"status": "pending_confirmation"},
        ),
    )
    repository = SqlAlchemyAgentRunProjectionRepository(db_session)
    repository.upsert(view)

    loaded = repository.get_by_run_id(view.run_id)

    assert loaded is not None
    assert loaded.evidence.confirmation.status == "pending"
    assert loaded.evidence.write_outcome.status == "pending_confirmation"
    assert loaded.decision_reason == view.decision_reason
    assert loaded.memory.items_used == 1
    assert loaded.memory.decision_influence == "context_only"
    assert loaded.operation_type == "memory_summary"
