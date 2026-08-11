from app.rag.retrieval.hybrid import HybridRetriever


class LocalKnowledgeBackend(HybridRetriever):
    """Deterministic in-process backend for tests, evaluation, and offline development."""
