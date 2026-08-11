from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.llm.base import StructuredDecisionProvider
from app.agent.schemas import StructuredDecision
from app.agent.state import ConversationMessage
from app.core.config import Settings

_PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "system.txt"


class OpenAICompatibleProvider(StructuredDecisionProvider):
    def __init__(self, settings: Settings) -> None:
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        self._model = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-needed",
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        ).with_structured_output(StructuredDecision)

    def decide(
        self, *, messages: Sequence[ConversationMessage], customer_id: int
    ) -> StructuredDecision:
        prompt_messages: list[BaseMessage] = [SystemMessage(content=self._system_prompt)]
        prompt_messages.append(
            SystemMessage(content=f"The authenticated customer_id is {customer_id}.")
        )
        for message in messages:
            message_type = HumanMessage if message["role"] == "user" else AIMessage
            prompt_messages.append(message_type(content=message["content"]))
        result = self._model.invoke(prompt_messages)
        return StructuredDecision.model_validate(result)
