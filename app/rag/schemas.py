from pydantic import BaseModel


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
    citation_id: str
    title: str
    source: str


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    grounded: bool
