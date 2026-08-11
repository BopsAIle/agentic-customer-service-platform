import re

from app.rag.schemas import DocumentChunk, KnowledgeDocument


def chunk_document(document: KnowledgeDocument, max_chars: int = 800) -> list[DocumentChunk]:
    sections = _sections(document.content)
    chunks: list[DocumentChunk] = []
    for section, content in sections:
        paragraphs = [part.strip() for part in content.split("\n\n") if part.strip()]
        current = ""
        index = 0
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > max_chars:
                chunks.append(_chunk(document, section, current, index))
                index += 1
                current = ""
            current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(_chunk(document, section, current, index))
    return chunks


def _sections(content: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = "overview"
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((slugify(current_title), "\n".join(current_lines)))
            current_title = line.removeprefix("## ").strip()
            current_lines = []
        elif not line.startswith("# "):
            current_lines.append(line)
    if current_lines:
        sections.append((slugify(current_title), "\n".join(current_lines)))
    return sections


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "overview"


def _chunk(document: KnowledgeDocument, section: str, content: str, index: int) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document.document_id}#{section}#{index}",
        document_id=document.document_id,
        title=document.title,
        category=document.category,
        section=section,
        source=document.source,
        chunk_index=index,
        content=content,
    )
