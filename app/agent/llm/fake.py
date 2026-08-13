from collections.abc import Iterable, Sequence

from app.agent.schemas import SemanticDecision, SemanticDecisionV3, StructuredDecision
from app.agent.state import ConversationMessage


class FakeDecisionProvider:
    """Deterministic provider for graph tests; it never contacts an LLM service."""

    def __init__(self, decisions: Iterable[StructuredDecision]) -> None:
        self._decisions = iter(decisions)
        self.calls: list[Sequence[ConversationMessage]] = []

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> StructuredDecision:
        self.calls.append(messages)
        return next(self._decisions)


class FakeSemanticDecisionProvider:
    """Deterministic semantic_decision_v2 provider for integration tests."""

    decision_contract_version = "semantic_decision_v2"

    def __init__(self, decisions: Iterable[SemanticDecision]) -> None:
        self._decisions = iter(decisions)
        self.calls: list[Sequence[ConversationMessage]] = []

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> SemanticDecision:
        del customer_id, memory_context
        self.calls.append(messages)
        return next(self._decisions)


class FakeSemanticDecisionV3Provider:
    """Deterministic semantic_decision_v3 provider for integration tests."""

    decision_contract_version = "semantic_decision_v3"

    def __init__(self, decisions: Iterable[SemanticDecisionV3]) -> None:
        self._decisions = iter(decisions)
        self.calls: list[Sequence[ConversationMessage]] = []

    def decide(
        self,
        *,
        messages: Sequence[ConversationMessage],
        customer_id: int,
        memory_context: Sequence[dict[str, object]] | None = None,
    ) -> SemanticDecisionV3:
        del customer_id, memory_context
        self.calls.append(messages)
        return next(self._decisions)
