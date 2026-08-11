from pathlib import Path

from app.rag.schemas import KnowledgeDocument


def load_markdown_documents(directory: Path) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = next(
            (
                line.removeprefix("# ").strip()
                for line in content.splitlines()
                if line.startswith("# ")
            ),
            path.stem.replace("-", " ").title(),
        )
        documents.append(
            KnowledgeDocument(
                document_id=path.stem,
                title=title,
                category=path.stem.removesuffix("-policy").replace("-", "_"),
                source=str(path),
                content=content,
            )
        )
    return documents
