from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent.decision_compiler import CompiledDecision, CompileStatus
from app.agent.schemas import AgentRequestType, AgentResponse, Intent
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
