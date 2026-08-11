from collections.abc import Sequence
from typing import Protocol

from app.agent.schemas import StructuredDecision
from app.agent.state import ConversationMessage


class StructuredDecisionProvider(Protocol):
    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> StructuredDecision: ...
