from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus, DecisionCompiler
from app.agent.schemas import AgentRequestType, Intent, SemanticDecision, SemanticTarget
from app.agent.semantic_grounding import GroundingStatus, validate_semantic_grounding
from app.agent.target_admissibility import (
    TargetAdmissibility,
    assess_target_admissibility,
)
from app.core.context import ExecutionContext


class SpyResolver(BusinessTargetResolver):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.calls = 0

    def resolve_order_id(
        self, target: SemanticTarget, customer_id: int, tenant_id: str = "default"
    ) -> int | None:
        self.calls += 1
        return super().resolve_order_id(target, customer_id, tenant_id)


def _decision(intent: Intent, target: SemanticTarget | None) -> SemanticDecision:
    return SemanticDecision(
        intent=intent,
        request_type=AgentRequestType.WRITE_ACTION,
        target=target,
    )


def test_symbolic_destructive_target_requires_clarification_before_resolver(
    db_session: Session,
) -> None:
    resolver = SpyResolver(db_session)
    target = SemanticTarget(type="latest_order")
    result = DecisionCompiler(resolver).compile(
        _decision(Intent.ORDER_CANCEL, target),
        _context(),
        grounding=validate_semantic_grounding(
            _decision(Intent.ORDER_CANCEL, target), "Cancel my order."
        ),
    )
    assert result.status == CompileStatus.CLARIFICATION_REQUIRED
    assert result.selected_tool is None
    assert resolver.calls == 0


def test_symbolic_refund_target_is_also_non_authoritative(db_session: Session) -> None:
    resolver = SpyResolver(db_session)
    target = SemanticTarget(type="latest_order")
    decision = _decision(Intent.REFUND_REQUEST, target)
    result = DecisionCompiler(resolver).compile(
        decision,
        _context(),
        grounding=validate_semantic_grounding(decision, "Refund my order."),
    )
    assert result.status == CompileStatus.CLARIFICATION_REQUIRED
    assert resolver.calls == 0


def test_symbolic_read_target_remains_customer_scoped_and_resolvable(
    db_session: Session,
) -> None:
    resolver = SpyResolver(db_session)
    target = SemanticTarget(type="latest_order")
    decision = _decision(Intent.ORDER_LOOKUP, target)
    result = DecisionCompiler(resolver).compile(
        decision,
        _context(customer_id=1),
        grounding=validate_semantic_grounding(decision, "Show my latest order."),
        user_message="Show my latest order.",
    )
    assert result.status == CompileStatus.COMPILED_ACTION
    assert result.selected_tool == "get_order"
    assert result.tool_arguments == {"customer_id": 1, "order_id": 4}
    assert resolver.calls == 1


def test_grounded_explicit_destructive_target_remains_admissible(db_session: Session) -> None:
    decision = _decision(
        Intent.ORDER_CANCEL,
        SemanticTarget(type="explicit_order", order_id=123),
    )
    grounding = validate_semantic_grounding(decision, "Cancel order 123.")
    assert grounding.status == GroundingStatus.GROUNDED
    assert assess_target_admissibility(decision.intent, decision.target, grounding) == (
        TargetAdmissibility.ADMISSIBLE
    )
    result = DecisionCompiler(BusinessTargetResolver(db_session)).compile(
        decision,
        _context(),
        grounding=grounding,
    )
    assert result.status == CompileStatus.COMPILED_ACTION
    assert result.proposed_write is not None
    assert result.proposed_write["tool"] == "cancel_order"


def test_symbolic_destructive_boundary_ignores_model_clarification_flag() -> None:
    target = SemanticTarget(type="latest_order")
    for clarification in (False, True):
        decision = SemanticDecision(
            intent=Intent.ORDER_CANCEL,
            request_type=AgentRequestType.WRITE_ACTION,
            target=target,
            clarification_required=clarification,
        )
        assert (
            assess_target_admissibility(
                decision.intent,
                decision.target,
                validate_semantic_grounding(decision, "Cancel my latest order."),
            )
            == TargetAdmissibility.REQUIRES_CLARIFICATION
        )


def _context(customer_id: int = 1) -> ExecutionContext:
    from app.auth.models import ActorType, Principal

    return ExecutionContext(
        request_id="admissibility-request",
        conversation_id="admissibility-conversation",
        principal=Principal(
            actor_id="admissibility-test",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=customer_id,
    )
