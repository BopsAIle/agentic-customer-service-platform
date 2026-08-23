from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class KnowledgeDocument(BaseModel):
    document_id: str
    title: str
    category: str
    source: str
    content: str


class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    category: str
    section: str
    source: str
    chunk_index: int
    content: str


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    category: str
    section: str
    source: str
    content: str
    score: float
    rerank_score: float | None = None

    @property
    def citation_id(self) -> str:
        return f"{self.document_id}#{self.section}"


class Citation(BaseModel):
    """Bounded evidence reference used by grounded answer generation."""

    citation_id: str
    document_id: str
    title: str
    chunk_id: str
    source: str
    relevance_score: float = Field(ge=0.0)
    quoted_excerpt: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_citation_projection(cls, value: Any) -> Any:
        """Accept pre-upgrade checkpoint citations without inventing evidence."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        citation_id = str(payload.get("citation_id", "unknown"))
        payload.setdefault("document_id", citation_id.split("#", maxsplit=1)[0])
        payload.setdefault("chunk_id", citation_id)
        payload.setdefault("relevance_score", 0.0)
        payload.setdefault("quoted_excerpt", "Excerpt unavailable from legacy citation projection.")
        return payload


class AnswerGroundingStatus(StrEnum):
    PASS = "pass"
    CONFLICT = "conflict"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"


class GroundingValidationResult(BaseModel):
    citation_coverage: float = Field(ge=0.0, le=1.0)
    accepted: bool
    unsupported_claim_count: int = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float = Field(ge=0.0, le=1.0)
    grounded_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    source_count: int = Field(ge=0)
    status: AnswerGroundingStatus
    validation: GroundingValidationResult
    grounded: bool = False
