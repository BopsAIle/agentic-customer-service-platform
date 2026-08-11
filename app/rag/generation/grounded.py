from collections.abc import Sequence

from app.rag.context import construct_context
from app.rag.schemas import Citation, GroundedAnswer, RetrievedChunk


class GroundedAnswerGenerator:
    def __init__(self, max_context: int = 4) -> None:
        self.max_context = max_context

    def answer(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        business_result: dict[str, object] | None = None,
    ) -> GroundedAnswer:
        context = construct_context(chunks, self.max_context)
        if not context:
            return GroundedAnswer(
                answer=(
                    "The knowledge base does not contain enough information "
                    "to answer that policy question."
                ),
                citations=[],
                grounded=False,
            )
        citations = [
            Citation(citation_id=chunk.citation_id, title=chunk.title, source=chunk.source)
            for chunk in context
        ]
        evidence = " ".join(f"{chunk.content.strip()} [{chunk.citation_id}]" for chunk in context)
        answer = evidence
        if business_result is not None:
            status = business_result.get("status")
            if isinstance(status, str):
                answer += (
                    f" The business system reports the specific resource status as '{status}'."
                )
            answer += " Business-system state is authoritative for the specific customer request."
        return GroundedAnswer(answer=answer, citations=citations, grounded=True)
