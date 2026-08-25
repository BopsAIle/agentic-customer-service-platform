"""Focused, provider-neutral RAG quality cases for release regression runs.

The cases describe expected evidence topics; they do not assert invented scores
or substitute for the grounding validator.  A runner can execute them against
the local snapshot or an isolated Qdrant snapshot and record observed results.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RagFocusCase:
    case_id: str
    query: str
    expected_topic: str
    expected_grounding: str


RAG_GROUNDING_FOCUS_CASES = (
    RagFocusCase("en_refund_eligibility", "What is your refund policy?", "eligibility", "grounded"),
    RagFocusCase(
        "en_refund_processing",
        "How long does a refund normally take?",
        "processing_time",
        "grounded",
    ),
    RagFocusCase(
        "en_refund_conditions", "What conditions apply to refunds?", "eligibility", "grounded"
    ),
    RagFocusCase(
        "en_crypto_unsupported",
        "Do you support cryptocurrency refunds?",
        "unsupported",
        "insufficient_evidence",
    ),
    RagFocusCase("tr_refund_conditions", "İade şartlarınız nelerdir?", "eligibility", "grounded"),
    RagFocusCase(
        "tr_refund_processing", "Param ne zaman hesabıma geçer?", "processing_time", "grounded"
    ),
    RagFocusCase(
        "tr_refund_eligibility_window", "İade uygunluk süresi nedir?", "eligibility", "grounded"
    ),
    RagFocusCase(
        "tr_unsupported_policy",
        "On yıl sonra iade yapabilir miyim?",
        "unsupported",
        "insufficient_evidence",
    ),
)


__all__ = ["RagFocusCase", "RAG_GROUNDING_FOCUS_CASES"]
