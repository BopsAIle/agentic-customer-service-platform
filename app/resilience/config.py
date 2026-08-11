from collections.abc import Callable
from dataclasses import dataclass
from time import sleep

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class ResilienceConfig:
    enabled: bool = True
    max_retries: int = 2
    initial_backoff_ms: int = 100
    max_backoff_ms: int = 500
    retrieval_timeout_seconds: float = 5.0
    tool_timeout_seconds: float = 10.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResilienceConfig":
        return cls(
            enabled=settings.resilience_enabled,
            max_retries=settings.resilience_max_retries,
            initial_backoff_ms=settings.resilience_initial_backoff_ms,
            max_backoff_ms=settings.resilience_max_backoff_ms,
            retrieval_timeout_seconds=settings.retrieval_timeout_seconds,
            tool_timeout_seconds=settings.tool_timeout_seconds,
        )


Sleeper = Callable[[float], None]


def default_sleeper(seconds: float) -> None:
    sleep(seconds)
