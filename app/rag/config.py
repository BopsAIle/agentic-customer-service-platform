from enum import StrEnum


class RagBackend(StrEnum):
    LOCAL = "local"
    QDRANT = "qdrant"


class EmbeddingProviderType(StrEnum):
    DETERMINISTIC = "deterministic"
    OPENAI = "openai"
    HUGGINGFACE = "huggingface"
