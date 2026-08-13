"""Deterministic compilation for the semantic_decision_v2 contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.schemas import (
    AgentRequestType,
    Intent,
    SemanticDecision,
    SemanticTarget,
)
from app.agent.semantic_grounding import SemanticGrounding
from app.agent.target_admissibility import (
    TargetAdmissibility,
    assess_target_admissibility,
)
from app.core.context import ExecutionContext
from app.memory.schemas import MemoryCandidate
from app.models import Order
from app.models.entities import EscalationPriority


class CompileStatus(StrEnum):
    COMPILED_ACTION = "compiled_action"
    CLARIFICATION_REQUIRED = "clarification_required"
    NO_ACTION = "no_action"
    COMPILE_REJECTED = "compile_rejected"


class CompiledDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CompileStatus
    intent: Intent
    request_type: AgentRequestType
    selected_tool: str | None = None
    tool_arguments: dict[str, object] = Field(default_factory=dict)
    requires_retrieval: bool = False
    knowledge_query: str | None = None
    memory_candidate: MemoryCandidate | None = None
    memory_key: str | None = None
    reason: str = ""
    rejection_reason: str | None = None


class BusinessTargetResolver:
    """Read-only, customer-scoped resolution of symbolic semantic references."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_order_id(self, target: SemanticTarget, customer_id: int) -> int | None:
        if target.type == "explicit_order":
            return target.order_id
        if target.type != "latest_order":
            return None
        order = self.session.scalar(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(1)
        )
        return order.id if order is not None else None


ACTION_TOOLS: Final[dict[Intent, str]] = {
    Intent.ORDER_CANCEL: "cancel_order",
    Intent.REFUND_REQUEST: "request_refund",
    Intent.TICKET_CREATE: "create_support_ticket",
    Intent.HUMAN_ESCALATION: "escalate_to_human",
}

READ_TOOLS: Final[dict[Intent, str]] = {
    Intent.CUSTOMER_LOOKUP: "get_customer",
    Intent.ORDER_LOOKUP: "get_order",
    Intent.ORDER_LIST: "get_customer_orders",
    Intent.TICKET_LOOKUP: "get_ticket",
    Intent.TICKET_LIST: "get_customer_tickets",
}

KNOWLEDGE_INTENTS: Final[frozenset[Intent]] = frozenset(
    {
        Intent.CAPABILITY_QUESTION,
        Intent.REFUND_POLICY,
        Intent.CANCELLATION_POLICY,
        Intent.SHIPPING_POLICY,
        Intent.SUPPORT_FAQ,
        Intent.REFUND_ELIGIBILITY,
        Intent.CANCELLATION_EXPLANATION,
    }
)

MEMORY_INTENTS: Final[frozenset[Intent]] = frozenset({Intent.MEMORY_REMEMBER, Intent.MEMORY_FORGET})

SEMANTIC_INTENT_ROUTES: Final[dict[Intent, str]] = {
    **{intent: "action" for intent in ACTION_TOOLS},
    **{intent: "read" for intent in READ_TOOLS},
    **{intent: "knowledge" for intent in KNOWLEDGE_INTENTS},
    **{intent: "memory" for intent in MEMORY_INTENTS},
    Intent.UNKNOWN: "clarification",
}


class DecisionCompiler:
    def __init__(self, resolver: BusinessTargetResolver) -> None:
        self.resolver = resolver

    def compile(
        self,
        decision: SemanticDecision,
        context: ExecutionContext,
        *,
        grounding: SemanticGrounding | None = None,
    ) -> CompiledDecision:
        admissibility = assess_target_admissibility(decision.intent, decision.target, grounding)
        if admissibility in {
            TargetAdmissibility.REQUIRES_CLARIFICATION,
            TargetAdmissibility.INVALID,
        }:
            return self._clarification(
                decision,
                "The request needs a specific, authorized target.",
            )
        route = SEMANTIC_INTENT_ROUTES.get(decision.intent)
        if route is None:
            return self._rejected(decision, "Semantic intent has no compiler route.")
        if route == "action":
            return self._compile_action(decision, context)
        if route == "read":
            return self._compile_read(decision, context)
        if route == "knowledge":
            return self._compile_knowledge(decision)
        if route == "memory":
            return self._compile_memory(decision)
        return self._clarification(decision, "The request needs clarification.")

    def _compile_action(
        self, decision: SemanticDecision, context: ExecutionContext
    ) -> CompiledDecision:
        tool = ACTION_TOOLS[decision.intent]
        if decision.intent in {Intent.ORDER_CANCEL, Intent.REFUND_REQUEST}:
            if self._wrong_order_target(decision.target):
                return self._rejected(decision, "Order action received a ticket target.")
            order_id = self._order_target(decision.target, context.effective_customer_id)
            if order_id is None:
                return self._clarification(decision, "A specific order is required.")
            if decision.intent == Intent.ORDER_CANCEL:
                return self._action(decision, context, tool, {"order_id": order_id})
            if not decision.reason:
                return self._clarification(decision, "A refund reason is required.")
            return self._action(
                decision, context, tool, {"order_id": order_id, "reason": decision.reason}
            )
        if decision.intent == Intent.TICKET_CREATE:
            if not decision.category or not decision.description:
                return self._clarification(
                    decision, "Ticket category and description are required."
                )
            order_id = None
            if decision.target is not None:
                if self._wrong_order_target(decision.target):
                    return self._rejected(decision, "Ticket creation received a ticket target.")
                order_id = self._order_target(decision.target, context.effective_customer_id)
                if order_id is None:
                    return self._clarification(
                        decision, "The referenced order could not be resolved."
                    )
            return self._action(
                decision,
                context,
                tool,
                {
                    "order_id": order_id,
                    "category": decision.category,
                    "description": decision.description,
                },
            )
        if decision.intent == Intent.HUMAN_ESCALATION:
            if not decision.reason or not decision.priority or not decision.summary:
                return self._clarification(decision, "Escalation details are required.")
            try:
                priority = EscalationPriority(decision.priority).value
            except ValueError:
                return self._rejected(decision, "Unsupported escalation priority.")
            escalated_order_id: int | None = None
            ticket_id: int | None = None
            if decision.target is not None:
                if decision.target.type in {"explicit_order", "latest_order"}:
                    escalated_order_id = self._order_target(
                        decision.target, context.effective_customer_id
                    )
                    if escalated_order_id is None:
                        return self._clarification(
                            decision, "The referenced order could not be resolved."
                        )
                elif decision.target.type == "explicit_ticket":
                    ticket_id = decision.target.ticket_id
            return self._action(
                decision,
                context,
                tool,
                {
                    "ticket_id": ticket_id,
                    "order_id": escalated_order_id,
                    "reason": decision.reason,
                    "priority": priority,
                    "summary": decision.summary,
                },
            )
        return self._rejected(decision, "Executable semantic intent is unsupported.")

    def _compile_read(
        self, decision: SemanticDecision, context: ExecutionContext
    ) -> CompiledDecision:
        tool = READ_TOOLS[decision.intent]
        if decision.intent == Intent.CUSTOMER_LOOKUP:
            if decision.target is not None:
                return self._rejected(decision, "Customer lookup does not accept a target.")
            return self._action(decision, context, tool, {})
        if decision.intent == Intent.ORDER_LIST:
            if decision.target is not None:
                return self._rejected(decision, "Order list does not accept a target.")
            return self._action(decision, context, tool, {})
        if decision.intent == Intent.TICKET_LIST:
            if decision.target is not None:
                return self._rejected(decision, "Ticket list does not accept a target.")
            return self._action(decision, context, tool, {})
        if decision.intent == Intent.ORDER_LOOKUP:
            if self._wrong_order_target(decision.target):
                return self._rejected(decision, "Order lookup received a ticket target.")
            order_id = self._order_target(decision.target, context.effective_customer_id)
            if order_id is None:
                return self._clarification(decision, "A specific order is required.")
            return self._action(decision, context, tool, {"order_id": order_id})
        if decision.intent == Intent.TICKET_LOOKUP:
            if decision.target is None or decision.target.type != "explicit_ticket":
                if decision.target is not None:
                    return self._rejected(decision, "Ticket lookup received a non-ticket target.")
                return self._clarification(decision, "A specific ticket is required.")
            return self._action(decision, context, tool, {"ticket_id": decision.target.ticket_id})
        return self._rejected(decision, "Read semantic intent is unsupported.")

    def _compile_knowledge(self, decision: SemanticDecision) -> CompiledDecision:
        if decision.clarification_required and not decision.knowledge_query:
            return self._clarification(decision, "The knowledge request needs clarification.")
        return CompiledDecision(
            status=CompileStatus.NO_ACTION,
            intent=decision.intent,
            request_type=decision.request_type,
            requires_retrieval=decision.requires_retrieval,
            knowledge_query=decision.knowledge_query,
            reason=decision.reason,
        )

    def _compile_memory(self, decision: SemanticDecision) -> CompiledDecision:
        if decision.intent == Intent.MEMORY_REMEMBER and decision.memory_candidate is None:
            return self._clarification(decision, "A specific memory is required.")
        if decision.intent == Intent.MEMORY_FORGET and not decision.memory_key:
            return self._clarification(decision, "A memory key is required.")
        return CompiledDecision(
            status=CompileStatus.NO_ACTION,
            intent=decision.intent,
            request_type=AgentRequestType.MEMORY_ACTION,
            memory_candidate=decision.memory_candidate,
            memory_key=decision.memory_key,
            reason=decision.reason,
        )

    def _order_target(self, target: SemanticTarget | None, customer_id: int) -> int | None:
        if target is None or target.type == "explicit_ticket":
            return None
        return self.resolver.resolve_order_id(target, customer_id)

    @staticmethod
    def _wrong_order_target(target: SemanticTarget | None) -> bool:
        return target is not None and target.type == "explicit_ticket"

    @staticmethod
    def _action(
        decision: SemanticDecision,
        context: ExecutionContext,
        tool: str,
        semantic_arguments: dict[str, object],
    ) -> CompiledDecision:
        return CompiledDecision(
            status=CompileStatus.COMPILED_ACTION,
            intent=decision.intent,
            request_type=(
                AgentRequestType.WRITE_ACTION
                if tool in ACTION_TOOLS.values()
                else AgentRequestType.READ_ACTION
            ),
            selected_tool=tool,
            tool_arguments={"customer_id": context.effective_customer_id, **semantic_arguments},
            reason=decision.reason,
        )

    @staticmethod
    def _clarification(decision: SemanticDecision, reason: str) -> CompiledDecision:
        return CompiledDecision(
            status=CompileStatus.CLARIFICATION_REQUIRED,
            intent=decision.intent,
            request_type=AgentRequestType.UNCLEAR,
            reason=reason,
        )

    @staticmethod
    def _rejected(decision: SemanticDecision, reason: str) -> CompiledDecision:
        return CompiledDecision(
            status=CompileStatus.COMPILE_REJECTED,
            intent=decision.intent,
            request_type=AgentRequestType.UNCLEAR,
            reason="The request could not be compiled safely.",
            rejection_reason=reason,
        )


def all_semantic_intents_are_routed() -> bool:
    return set(SEMANTIC_INTENT_ROUTES) == set(Intent)
