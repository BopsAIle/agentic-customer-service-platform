"""Deterministic audit for citation-constrained grounded answer generation."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.rag.answer_generator import GroundedAnswerGenerator
from app.rag.schemas import AnswerGroundingStatus, RetrievedChunk

AUDIT_VERSION = "rag_grounding_audit_v1"


@dataclass(frozen=True, slots=True)
class GroundingCase:
    case_id: str
    question: str
    evidence: tuple[RetrievedChunk, ...]
    expected_status: AnswerGroundingStatus
    minimum_citations: int
    expected_accepted: bool


class GroundingCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    passed: bool
    status: AnswerGroundingStatus
    citation_count: int = Field(ge=0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    accepted: bool


class RagGroundingAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: str = AUDIT_VERSION
    case_count: int
    passed_count: int
    failed_count: int
    citation_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_count: int = Field(ge=0)
    retrieval_count: int = Field(ge=0)
    answer_confidence: float = Field(ge=0.0, le=1.0)
    model_calls_performed: int = 0
    results: tuple[GroundingCaseResult, ...]


def _chunk(
    case_id: str,
    content: str,
    *,
    document_id: str | None = None,
    score: float = 0.9,
) -> RetrievedChunk:
    document = document_id or f"{case_id}-policy"
    return RetrievedChunk(
        chunk_id=f"{document}#section#0",
        document_id=document,
        title=document.replace("-", " ").title(),
        category="policy",
        section="section",
        source=f"knowledge/{document}.md",
        content=content,
        score=score,
    )


def grounding_cases() -> tuple[GroundingCase, ...]:
    grounded = [
        (
            "refund-policy",
            "What is the refund policy?",
            "Refund requests are reviewed within 30 days.",
        ),
        (
            "shipping-policy",
            "What is the shipping policy?",
            "Shipping times depend on the selected carrier.",
        ),
        (
            "cancel-policy",
            "Can shipped orders be cancelled?",
            "Shipped orders cannot be cancelled through self-service.",
        ),
        ("warranty", "How long is the warranty?", "The standard warranty lasts 12 months."),
        (
            "damaged-return",
            "Can damaged products be returned?",
            "Damaged products may be returned after verification.",
        ),
        (
            "support-hours",
            "What are support hours?",
            "Support hours are listed as 09:00 to 17:00 UTC.",
        ),
        (
            "payment",
            "Which payment methods are accepted?",
            "Accepted payment methods include cards and bank transfer.",
        ),
        (
            "account-security",
            "How is account security verified?",
            "Account security requires identity verification.",
        ),
        (
            "delivery-tracking",
            "How can delivery be tracked?",
            "Delivery tracking is available from the order page.",
        ),
        (
            "exchange",
            "What is the exchange policy?",
            "Product exchanges require an eligible order.",
        ),
        (
            "privacy",
            "What customer privacy controls apply?",
            "Customer privacy requests require identity verification.",
        ),
        (
            "ticket",
            "How are support tickets prioritized?",
            "Support tickets are prioritized by documented severity.",
        ),
    ]
    cases = [
        GroundingCase(
            case_id=case_id,
            question=question,
            evidence=(_chunk(case_id, content),),
            expected_status=AnswerGroundingStatus.PASS,
            minimum_citations=1,
            expected_accepted=True,
        )
        for case_id, question, content in grounded
    ]
    cases.extend(
        [
            GroundingCase(
                case_id="hallucination-ceo-phone",
                question="What is the CEO phone number?",
                evidence=(
                    _chunk("refund-unrelated", "Refund requests require an eligible order."),
                ),
                expected_status=AnswerGroundingStatus.INSUFFICIENT_EVIDENCE,
                minimum_citations=0,
                expected_accepted=False,
            ),
            GroundingCase(
                case_id="hallucination-price",
                question="What is the private enterprise price?",
                evidence=(_chunk("shipping-unrelated", "Shipping times depend on the carrier."),),
                expected_status=AnswerGroundingStatus.INSUFFICIENT_EVIDENCE,
                minimum_citations=0,
                expected_accepted=False,
            ),
            GroundingCase(
                case_id="empty-refund",
                question="What is the refund policy?",
                evidence=(),
                expected_status=AnswerGroundingStatus.INSUFFICIENT_EVIDENCE,
                minimum_citations=0,
                expected_accepted=False,
            ),
            GroundingCase(
                case_id="empty-shipping",
                question="What is the shipping policy?",
                evidence=(),
                expected_status=AnswerGroundingStatus.INSUFFICIENT_EVIDENCE,
                minimum_citations=0,
                expected_accepted=False,
            ),
            GroundingCase(
                case_id="refund-conflict",
                question="How many days does the refund policy allow?",
                evidence=(
                    _chunk("refund-30", "Refund requests are allowed within 30 days."),
                    _chunk("refund-14", "Refund requests are allowed within 14 days."),
                ),
                expected_status=AnswerGroundingStatus.CONFLICT,
                minimum_citations=2,
                expected_accepted=True,
            ),
            GroundingCase(
                case_id="warranty-conflict",
                question="How many months is the warranty?",
                evidence=(
                    _chunk("warranty-12", "The warranty lasts 12 months."),
                    _chunk("warranty-24", "The warranty lasts 24 months."),
                ),
                expected_status=AnswerGroundingStatus.CONFLICT,
                minimum_citations=2,
                expected_accepted=True,
            ),
            GroundingCase(
                case_id="multi-source-refund",
                question="What evidence supports damaged product refunds?",
                evidence=(
                    _chunk("refund-eligibility", "Damaged products may qualify for refund review."),
                    _chunk(
                        "damage-verification", "Damaged products require verification evidence."
                    ),
                ),
                expected_status=AnswerGroundingStatus.PASS,
                minimum_citations=2,
                expected_accepted=True,
            ),
            GroundingCase(
                case_id="duplicate-evidence",
                question="What is the refund review policy?",
                evidence=(
                    _chunk(
                        "refund-copy-a",
                        "Refund review requires an eligible order.",
                        document_id="refund-policy",
                    ),
                    _chunk(
                        "refund-copy-b",
                        "Refund review requires an eligible order.",
                        document_id="refund-policy",
                    ),
                ),
                expected_status=AnswerGroundingStatus.PASS,
                minimum_citations=1,
                expected_accepted=True,
            ),
        ]
    )
    if len(cases) != 20:
        raise AssertionError("rag grounding audit must contain exactly 20 cases")
    return tuple(cases)


def run_audit() -> RagGroundingAudit:
    generator = GroundedAnswerGenerator(max_context=4)
    results: list[GroundingCaseResult] = []
    cases = grounding_cases()
    for case in cases:
        answer = generator.answer(case.question, case.evidence)
        passed = (
            answer.status == case.expected_status
            and len(answer.citations) >= case.minimum_citations
            and answer.validation.accepted is case.expected_accepted
            and not answer.unsupported_claims
        )
        results.append(
            GroundingCaseResult(
                case_id=case.case_id,
                passed=passed,
                status=answer.status,
                citation_count=len(answer.citations),
                citation_coverage=answer.validation.citation_coverage,
                unsupported_claim_count=len(answer.unsupported_claims),
                confidence=answer.confidence,
                accepted=answer.validation.accepted,
            )
        )
    retrieval_count = sum(len(case.evidence) for case in cases)
    answers_with_citations = [result for result in results if result.citation_count]
    citation_coverage = sum(result.citation_coverage for result in answers_with_citations) / len(
        answers_with_citations
    )
    return RagGroundingAudit(
        case_count=len(results),
        passed_count=sum(result.passed for result in results),
        failed_count=sum(not result.passed for result in results),
        citation_coverage=citation_coverage,
        unsupported_claim_count=sum(result.unsupported_claim_count for result in results),
        retrieval_count=retrieval_count,
        answer_confidence=sum(result.confidence for result in results) / len(results),
        results=tuple(results),
    )


def main() -> int:
    audit = run_audit()
    print(f"RAG grounding: {audit.passed_count}/{audit.case_count}")
    print(f"Citation coverage: {audit.citation_coverage:.1%}")
    print(f"Unsupported claims: {audit.unsupported_claim_count}")
    return 0 if audit.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
