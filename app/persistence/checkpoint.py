from __future__ import annotations

import hashlib
import logging
from enum import StrEnum
from math import ceil
from typing import Protocol
from urllib.parse import quote

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.agent.schemas import AgentErrorCategory, AgentRequestType, Intent
from app.auth.models import ActorType, Principal
from app.core.config import Settings
from app.core.context import ExecutionContext
from app.memory.schemas import MemoryCandidate, MemoryType
from app.policies.models import PendingAction, PendingActionStatus, PolicyDecision, PolicyOutcome

logger = logging.getLogger(__name__)


class CheckpointBackend(StrEnum):
    POSTGRES = "postgres"
    MEMORY = "memory"


class CheckpointProvider(Protocol):
    """Application boundary around the LangGraph checkpoint backend lifecycle."""

    @property
    def backend(self) -> CheckpointBackend: ...

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]: ...

    def initialize(self) -> None: ...

    def close(self) -> None: ...


class MemoryCheckpointProvider:
    """Deterministic process-local provider for tests and explicit local use."""

    def __init__(self, checkpointer: MemorySaver | None = None) -> None:
        self._checkpointer = checkpointer or MemorySaver(serde=_checkpoint_serializer())

    @property
    def backend(self) -> CheckpointBackend:
        return CheckpointBackend.MEMORY

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]:
        return self._checkpointer

    def initialize(self) -> None:
        return None

    def close(self) -> None:
        return None


class PostgresCheckpointProvider:
    """Managed official LangGraph PostgreSQL checkpoint provider."""

    def __init__(
        self,
        database_url: str,
        *,
        connect_timeout_seconds: float = 5.0,
        statement_timeout_seconds: float = 10.0,
        pool_timeout_seconds: float = 5.0,
    ) -> None:
        conninfo = _psycopg_conninfo(database_url)
        self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            conninfo=conninfo,
            min_size=1,
            max_size=10,
            open=False,
            timeout=pool_timeout_seconds,
            kwargs={
                "autocommit": True,
                "connect_timeout": ceil(connect_timeout_seconds),
                "options": f"-c statement_timeout={ceil(statement_timeout_seconds * 1000)}",
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        self._checkpointer = PostgresSaver(self._pool, serde=_checkpoint_serializer())
        self._initialized = False

    @property
    def backend(self) -> CheckpointBackend:
        return CheckpointBackend.POSTGRES

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]:
        return self._checkpointer

    def initialize(self) -> None:
        if self._initialized:
            return
        try:
            self._pool.open(wait=True)
            self._checkpointer.setup()
        except Exception as error:
            self._pool.close()
            logger.error(
                "Checkpoint persistence initialization failed.",
                extra={
                    "checkpoint_backend": self.backend.value,
                    "persistence_error_type": type(error).__name__,
                },
            )
            raise RuntimeError("Checkpoint persistence initialization failed.") from None
        self._initialized = True

    def close(self) -> None:
        if not self._initialized:
            return
        self._pool.close()
        self._initialized = False


def build_checkpoint_provider(settings: Settings) -> CheckpointProvider:
    backend = CheckpointBackend(settings.checkpoint_backend)
    if backend == CheckpointBackend.MEMORY:
        return MemoryCheckpointProvider()
    return PostgresCheckpointProvider(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
        statement_timeout_seconds=settings.database_query_timeout_seconds,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
    )


def checkpoint_thread_id(context: ExecutionContext) -> str:
    """Return a collision-safe, actor/customer-scoped LangGraph thread identity."""

    principal = context.principal
    actor_id = quote(principal.actor_id, safe="")
    conversation_id = quote(context.conversation_id, safe="")
    return (
        f"v1:{principal.actor_type.value}:{actor_id}:"
        f"customer-{context.effective_customer_id}:{conversation_id}"
    )


def checkpoint_thread_id_hash(context: ExecutionContext) -> str:
    """Return a bounded identifier suitable for logs and tracing."""

    value = checkpoint_thread_id(context).encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def _psycopg_conninfo(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if database_url.startswith("postgres+psycopg://"):
        return database_url.replace("postgres+psycopg://", "postgresql://", 1)
    return database_url


def _checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            ExecutionContext,
            Principal,
            ActorType,
            Intent,
            AgentRequestType,
            AgentErrorCategory,
            PendingAction,
            PendingActionStatus,
            PolicyDecision,
            PolicyOutcome,
            MemoryCandidate,
            MemoryType,
        )
    )
