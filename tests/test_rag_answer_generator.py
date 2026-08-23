from app.rag.answer_generator import GroundedAnswerGenerator, GroundingValidator
from app.rag.schemas import (
    AnswerGroundingStatus,
    Citation,
    GroundedAnswer,
    GroundingValidationResult,
    RetrievedChunk,
)


def _chunk(
    content: str, *, document_id: str = "refund-policy", score: float = 0.9
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{document_id}#eligibility#0",
        document_id=document_id,
        title="Refund Policy",
        category="refund",
        section="eligibility",
        source=f"knowledge/{document_id}.md",
        content=content,
        score=score,
    )


def test_generated_factual_claims_are_covered_by_retrieved_citations() -> None:
    evidence = _chunk("Damaged products may qualify for refund review within 30 days.")

    answer = GroundedAnswerGenerator().answer("refund policy for damaged products", [evidence])

    assert answer.status == AnswerGroundingStatus.PASS
    assert answer.validation.accepted is True
    assert answer.validation.citation_coverage == 1.0
    assert answer.citations[0].chunk_id == evidence.chunk_id
    assert answer.citations[0].quoted_excerpt in evidence.content
    assert answer.source_count == 1
    assert answer.unsupported_claims == []


def test_irrelevant_retrieval_fails_closed_without_repeating_evidence() -> None:
    evidence = _chunk("Refund requests require an eligible order.")

    answer = GroundedAnswerGenerator().answer("What is the CEO phone number?", [evidence])

    assert answer.status == AnswerGroundingStatus.INSUFFICIENT_EVIDENCE
    assert answer.validation.accepted is False
    assert answer.citations == []
    assert answer.confidence == 0.0
    assert "phone" not in answer.answer.casefold()


def test_conflicting_evidence_is_surfaced_without_silent_selection() -> None:
    evidence = [
        _chunk("Refund requests are allowed within 30 days.", document_id="refund-v3"),
        _chunk("Refund requests are allowed within 14 days.", document_id="refund-v2"),
    ]

    answer = GroundedAnswerGenerator().answer(
        "How many days does the refund policy allow?", evidence
    )

    assert answer.status == AnswerGroundingStatus.CONFLICT
    assert answer.validation.accepted is True
    assert len(answer.citations) == 2
    assert "conflict" in answer.answer.casefold()
    assert "30 days" in answer.answer
    assert "14 days" in answer.answer


def test_validator_rejects_uncited_claim_and_mismatched_excerpt() -> None:
    evidence = _chunk("Refund requests require an eligible order.")
    candidate = GroundedAnswer(
        answer="Refunds are always automatic.",
        citations=[
            Citation(
                citation_id=evidence.citation_id,
                document_id=evidence.document_id,
                title=evidence.title,
                chunk_id=evidence.chunk_id,
                source=evidence.source,
                relevance_score=evidence.score,
                quoted_excerpt="This text was not retrieved.",
            )
        ],
        confidence=0.9,
        grounded_claims=["Refunds are always automatic"],
        unsupported_claims=[],
        source_count=1,
        status=AnswerGroundingStatus.PASS,
        validation=GroundingValidationResult(
            citation_coverage=0.0,
            accepted=False,
            unsupported_claim_count=0,
        ),
    )

    validation = GroundingValidator().validate(candidate, [evidence])

    assert validation.accepted is False
    assert validation.citation_coverage == 0.0
    assert validation.unsupported_claim_count == 1
    assert "citation_excerpt_mismatch" in validation.reasons


def test_validator_rejects_answer_mismatch_even_with_valid_citation_marker() -> None:
    evidence = _chunk("Refund requests require an eligible order.")
    claim = "Refunds are always automatic"
    candidate = GroundedAnswer(
        answer=f"{claim} [{evidence.citation_id}].",
        citations=[
            Citation(
                citation_id=evidence.citation_id,
                document_id=evidence.document_id,
                title=evidence.title,
                chunk_id=evidence.chunk_id,
                source=evidence.source,
                relevance_score=evidence.score,
                quoted_excerpt="Refund requests require an eligible order",
            )
        ],
        confidence=0.9,
        grounded_claims=[claim],
        unsupported_claims=[],
        source_count=1,
        status=AnswerGroundingStatus.PASS,
        validation=GroundingValidationResult(
            citation_coverage=0.0,
            accepted=False,
            unsupported_claim_count=0,
        ),
    )

    validation = GroundingValidator().validate(candidate, [evidence])

    assert validation.accepted is False
    assert validation.unsupported_claim_count == 1
    assert "answer_evidence_mismatch" in validation.reasons
