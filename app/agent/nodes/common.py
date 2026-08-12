from pydantic import BaseModel

from app.agent.errors import RuntimeFailureSource, classify_runtime_error
from app.agent.schemas import AgentErrorCategory


def error_category(error: Exception) -> AgentErrorCategory:
    return classify_runtime_error(error, source=RuntimeFailureSource.TOOL).category


def serialise_result(result: object) -> dict[str, object]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in result
            ]
        }
    return {"value": result}
