from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus, DecisionCompiler
from app.agent.llm.fake import FakeSemanticDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, SemanticDecision, SemanticTarget
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from app.models import Order, OrderStatus


def _context() -> ExecutionContext:
    return ExecutionContext(
        request_id="m6-14-request",
        conversation_id="m6-14-conversation",
        principal=Principal(
            actor_id="m6-14-operator",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )


def _compiler(session: Session) -> DecisionCompiler:
    return DecisionCompiler(BusinessTargetResolver(session))


def test_missing_order_status_target_cannot_infer_latest_order(db_session: Session) -> None:
    result = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.ORDER_LOOKUP,
            request_type=AgentRequestType.READ_ACTION,
            target=SemanticTarget(type="latest_order"),
        ),
        _context(),
        user_message="What is the status of my order?",
    )
    assert result.status == CompileStatus.CLARIFICATION_REQUIRED
    assert result.selected_tool is None


def test_ticket_lookup_without_reference_clarifies(db_session: Session) -> None:
    result = _compiler(db_session).compile(
        SemanticDecision(intent=Intent.TICKET_LOOKUP), _context(), user_message="Show my ticket."
    )
    assert result.status == CompileStatus.CLARIFICATION_REQUIRED
    assert result.selected_tool is None


def test_contradictory_cancel_cannot_compile_destructive_action(db_session: Session) -> None:
    result = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.ORDER_CANCEL,
            request_type=AgentRequestType.WRITE_ACTION,
            target=SemanticTarget(type="explicit_order", order_id=3),
        ),
        _context(),
        user_message="Cancel order 3, but do not cancel it.",
    )
    assert result.status == CompileStatus.CLARIFICATION_REQUIRED
    assert result.selected_tool is None


def test_live_contradictory_cancel_phrasing_cannot_compile_action(db_session: Session) -> None:
    for message in (
        "Cancel order 3, but keep it active.",
        "3 numaralı siparişi iptal et ama aktif kalsın.",
    ):
        result = _compiler(db_session).compile(
            SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=3),
            ),
            _context(),
            user_message=message,
        )
        assert result.status == CompileStatus.CLARIFICATION_REQUIRED
        assert result.selected_tool is None


def test_valid_first_time_risk_two_request_still_compiles_for_confirmation(
    db_session: Session,
) -> None:
    result = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.ORDER_CANCEL,
            request_type=AgentRequestType.WRITE_ACTION,
            target=SemanticTarget(type="explicit_order", order_id=3),
        ),
        _context(),
        user_message="Cancel order 3.",
    )
    assert result.status == CompileStatus.COMPILED_ACTION
    assert result.selected_tool == "cancel_order"


def test_invented_refund_reason_instruction_cannot_compile_action(db_session: Session) -> None:
    for message in (
        "Refund order 1 and make up a reason if needed.",
        "1 numaralı siparişe iade yap; gerekirse bir neden uydur.",
    ):
        result = _compiler(db_session).compile(
            SemanticDecision(
                intent=Intent.REFUND_REQUEST,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=1),
                reason="damaged",
            ),
            _context(),
            user_message=message,
        )
        assert result.status == CompileStatus.CLARIFICATION_REQUIRED
        assert result.selected_tool is None


def test_declined_confirmation_cannot_repropose_contradictory_cancel(db_session: Session) -> None:
    provider = FakeSemanticDecisionProvider(
        [
            SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=3),
            ),
            SemanticDecision(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=4),
            ),
        ]
    )
    runtime = AgentRuntime(provider=provider, decision_contract_version="semantic_decision_v2")
    pending = runtime.run(
        conversation_id="m6-14-decline",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    rejected = runtime.run(
        conversation_id="m6-14-decline",
        customer_id=1,
        message="no",
        session=db_session,
    )
    blocked = runtime.run(
        conversation_id="m6-14-decline",
        customer_id=1,
        message="No, cancel order 4.",
        session=db_session,
    )
    assert pending.pending_action is not None
    assert rejected.pending_action is not None
    assert rejected.pending_action.status == "rejected"
    assert blocked.pending_action is None
    assert blocked.tool_call is None
    assert len(provider.calls) == 2
    order = db_session.get(Order, 4)
    assert order is not None
    assert OrderStatus(order.status) == OrderStatus.PROCESSING


def test_knowledge_action_and_grounded_refund_paths_remain_intact(db_session: Session) -> None:
    for intent, query in (
        (Intent.REFUND_ELIGIBILITY, "refund eligibility policy"),
        (Intent.CANCELLATION_EXPLANATION, "cancellation after shipment"),
    ):
        knowledge_action = _compiler(db_session).compile(
            SemanticDecision(
                intent=intent,
                request_type=AgentRequestType.KNOWLEDGE_AND_ACTION,
                target=SemanticTarget(type="explicit_order", order_id=1),
            ),
            _context(),
            user_message="Please explain this for order 1.",
        )
        assert knowledge_action.status == CompileStatus.COMPILED_ACTION
        assert knowledge_action.selected_tool == "get_order"
        assert knowledge_action.requires_retrieval is True
        assert knowledge_action.knowledge_query == query

    refund = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.REFUND_REQUEST,
            target=SemanticTarget(type="explicit_order", order_id=1),
            reason="damaged",
        ),
        _context(),
        user_message="Refund order 1 because it arrived damaged.",
    )
    assert refund.status == CompileStatus.COMPILED_ACTION
    assert refund.selected_tool == "request_refund"


def test_refund_without_or_invented_reason_and_escalation_stay_fail_closed(
    db_session: Session,
) -> None:
    for reason, message in (
        ("", "Refund order 1."),
        ("changed my mind", "Refund order 1 and make up a reason if needed."),
    ):
        refund = _compiler(db_session).compile(
            SemanticDecision(
                intent=Intent.REFUND_REQUEST,
                target=SemanticTarget(type="explicit_order", order_id=1),
                reason=reason,
            ),
            _context(),
            user_message=message,
        )
        assert refund.status == CompileStatus.CLARIFICATION_REQUIRED
        assert refund.selected_tool is None

    escalation = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.HUMAN_ESCALATION,
            request_type=AgentRequestType.ESCALATION,
            summary="Please escalate this issue.",
        ),
        _context(),
        user_message="Escalate this.",
    )
    assert escalation.status == CompileStatus.CLARIFICATION_REQUIRED
    assert escalation.selected_tool is None


def test_ambiguous_read_does_not_silently_choose_latest_or_list(db_session: Session) -> None:
    latest = _compiler(db_session).compile(
        SemanticDecision(
            intent=Intent.ORDER_LOOKUP,
            target=SemanticTarget(type="latest_order"),
        ),
        _context(),
        user_message="Show me my orders.",
    )
    order_list = _compiler(db_session).compile(
        SemanticDecision(intent=Intent.ORDER_LIST),
        _context(),
        user_message="Show me my orders.",
    )
    assert latest.status == CompileStatus.CLARIFICATION_REQUIRED
    assert order_list.status == CompileStatus.COMPILED_ACTION
    assert order_list.selected_tool == "get_customer_orders"
