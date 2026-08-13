from collections.abc import Sequence
from typing import Protocol

from app.agent.schemas import SemanticDecision, SemanticDecisionV3, StructuredDecision
from app.agent.state import ConversationMessage

DecisionProposal = StructuredDecision | SemanticDecision | SemanticDecisionV3


class StructuredDecisionProvider(Protocol):
    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> StructuredDecision: ...


class DecisionProposalProvider(Protocol):
    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> DecisionProposal: ...
