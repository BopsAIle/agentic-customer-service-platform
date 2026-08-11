from app.resilience.errors import FailureCategory


def degraded_message(category: FailureCategory, *, knowledge_only: bool) -> str:
    if category in {
        FailureCategory.RETRIEVAL_TIMEOUT,
        FailureCategory.RETRIEVAL_UNAVAILABLE,
        FailureCategory.EMBEDDING_FAILURE,
        FailureCategory.RERANKER_FAILURE,
    }:
        return (
            "I can't reliably retrieve the support knowledge right now, so I won't guess."
            if knowledge_only
            else (
                "I couldn't retrieve the policy knowledge right now, so I won't claim "
                "exact policy details."
            )
        )
    if category == FailureCategory.MEMORY_FAILURE:
        return "I couldn't update persistent memory, but I can continue with this request."
    if category in {
        FailureCategory.LLM_TIMEOUT,
        FailureCategory.LLM_UNAVAILABLE,
        FailureCategory.LLM_MALFORMED_OUTPUT,
    }:
        return "I couldn't understand that request reliably. Please rephrase it."
    if category == FailureCategory.POLICY_FAILURE:
        return (
            "I couldn't safely evaluate authorization for that operation, so I did not execute it."
        )
    return "I couldn't complete that request safely. Please try again."
