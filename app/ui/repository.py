from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import AgentRunProjectionRecord
from app.ui.schemas import AgentRunView

DEFAULT_PROJECTION_QUERY_LIMIT = 50
MAX_PROJECTION_QUERY_LIMIT = 100
DEFAULT_PROJECTION_MEMORY_LIMIT = 500


class AgentRunProjectionRepository(Protocol):
    """Observational operator read-model storage; never an execution authority."""

    def upsert(self, projection: AgentRunView) -> None: ...

    def get_by_run_id(self, run_id: str) -> AgentRunView | None: ...

    def list_recent(self, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT) -> list[AgentRunView]: ...

    def list_for_customer(
        self, customer_id: int, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]: ...

    def list_for_conversation(
        self, conversation_id: str, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]: ...


class InMemoryAgentRunProjectionRepository:
    """Bounded, thread-safe, non-production projection adapter for tests/local use."""

    def __init__(self, max_projections: int = DEFAULT_PROJECTION_MEMORY_LIMIT) -> None:
        if max_projections < 1:
            raise ValueError("max_projections must be positive")
        self.max_projections = max_projections
        self._lock = RLock()
        self._projections: dict[str, AgentRunView] = {}

    def upsert(self, projection: AgentRunView) -> None:
        with self._lock:
            existing = self._projections.get(projection.run_id)
            if existing is not None:
                projection = projection.model_copy(update={"started_at": existing.started_at})
            self._projections[projection.run_id] = projection
            while len(self._projections) > self.max_projections:
                oldest_run_id = min(
                    self._projections,
                    key=lambda run_id: (
                        self._projections[run_id].started_at,
                        run_id,
                    ),
                )
                del self._projections[oldest_run_id]

    def get_by_run_id(self, run_id: str) -> AgentRunView | None:
        with self._lock:
            return self._projections.get(run_id)

    def list_recent(self, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT) -> list[AgentRunView]:
        with self._lock:
            return _sort_recent(list(self._projections.values()), limit)

    def list_for_customer(
        self, customer_id: int, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]:
        with self._lock:
            return _sort_recent(
                [
                    projection
                    for projection in self._projections.values()
                    if projection.customer_id == customer_id
                ],
                limit,
            )

    def list_for_conversation(
        self, conversation_id: str, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]:
        with self._lock:
            matching = [
                projection
                for projection in self._projections.values()
                if projection.conversation_id == conversation_id
            ]
            return _sort_recent(matching, limit)[::-1]


class SqlAlchemyAgentRunProjectionRepository:
    """PostgreSQL/SQLAlchemy projection repository with bounded deterministic reads."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, projection: AgentRunView) -> None:
        record = self.session.scalar(
            select(AgentRunProjectionRecord).where(
                AgentRunProjectionRecord.run_id == projection.run_id
            )
        )
        try:
            if record is None:
                self.session.add(_to_record(projection))
            else:
                _update_record(record, projection)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            record = self.session.scalar(
                select(AgentRunProjectionRecord).where(
                    AgentRunProjectionRecord.run_id == projection.run_id
                )
            )
            if record is None:
                raise
            _update_record(record, projection)
            self.session.commit()

    def get_by_run_id(self, run_id: str) -> AgentRunView | None:
        record = self.session.scalar(
            select(AgentRunProjectionRecord).where(AgentRunProjectionRecord.run_id == run_id)
        )
        return _from_record(record) if record is not None else None

    def list_recent(self, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT) -> list[AgentRunView]:
        return self._list(select(AgentRunProjectionRecord), limit, newest_first=True)

    def list_for_customer(
        self, customer_id: int, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]:
        return self._list(
            select(AgentRunProjectionRecord).where(
                AgentRunProjectionRecord.effective_customer_id == customer_id
            ),
            limit,
            newest_first=True,
        )

    def list_for_conversation(
        self, conversation_id: str, *, limit: int = DEFAULT_PROJECTION_QUERY_LIMIT
    ) -> list[AgentRunView]:
        return self._list(
            select(AgentRunProjectionRecord).where(
                AgentRunProjectionRecord.conversation_id == conversation_id
            ),
            limit,
            newest_first=False,
        )

    def _list(
        self,
        statement: Select[tuple[AgentRunProjectionRecord]],
        limit: int,
        *,
        newest_first: bool,
    ) -> list[AgentRunView]:
        bounded = _bounded_limit(limit)
        ordered = statement.order_by(
            AgentRunProjectionRecord.created_at.desc(),
            AgentRunProjectionRecord.id.desc(),
        )
        rows = list(self.session.scalars(ordered.limit(bounded)))
        if not newest_first:
            rows.reverse()
        return [_from_record(row) for row in rows]


def build_agent_run_projection_repository(
    settings: object, session: Session | None = None
) -> AgentRunProjectionRepository:
    backend = getattr(settings, "agent_run_projection_backend", "memory")
    if backend == "memory":
        from app.ui.projection import get_projection_store

        return get_projection_store()
    if session is None:
        raise ValueError("A database session is required for PostgreSQL projections.")
    return SqlAlchemyAgentRunProjectionRepository(session)


def _to_record(projection: AgentRunView) -> AgentRunProjectionRecord:
    payload = projection.model_dump(mode="json")
    return AgentRunProjectionRecord(
        run_id=projection.run_id,
        request_id=projection.request_id,
        conversation_id=projection.conversation_id,
        effective_customer_id=projection.customer_id,
        actor_id=projection.actor_id,
        actor_type=projection.actor_type,
        roles=payload["roles"],
        intent=projection.intent,
        request_type=projection.request_type,
        status=projection.status,
        started_at=projection.started_at,
        duration_ms=projection.duration_ms,
        trace_id=projection.trace_id,
        path=payload["path"],
        failure_category=projection.failure_category,
        degraded_components=payload["degraded_components"],
        recovery_action=projection.recovery_action,
        memory_item_count=projection.memory.item_count,
        memory_keys=payload["memory"]["keys"],
        memory_types=payload["memory"]["types"],
        tools=payload["tools"],
        policy=payload["policy"],
        rag_documents=payload["rag_documents"],
        retrieval_metadata=payload["retrieval_metadata"],
        trace=payload["trace"],
        created_at=projection.started_at,
        updated_at=datetime.now(UTC),
    )


def _update_record(record: AgentRunProjectionRecord, projection: AgentRunView) -> None:
    replacement = _to_record(projection)
    stored_updated_at = record.updated_at
    if stored_updated_at.tzinfo is None:
        stored_updated_at = stored_updated_at.replace(tzinfo=UTC)
    if replacement.updated_at <= stored_updated_at:
        replacement.updated_at = stored_updated_at + timedelta(microseconds=1)
    for field in (
        "request_id",
        "conversation_id",
        "effective_customer_id",
        "actor_id",
        "actor_type",
        "roles",
        "intent",
        "request_type",
        "status",
        "duration_ms",
        "trace_id",
        "path",
        "failure_category",
        "degraded_components",
        "recovery_action",
        "memory_item_count",
        "memory_keys",
        "memory_types",
        "tools",
        "policy",
        "rag_documents",
        "retrieval_metadata",
        "trace",
        "updated_at",
    ):
        setattr(record, field, getattr(replacement, field))


def _from_record(record: AgentRunProjectionRecord) -> AgentRunView:
    return AgentRunView.model_validate(
        {
            "run_id": record.run_id,
            "request_id": record.request_id,
            "conversation_id": record.conversation_id,
            "customer_id": record.effective_customer_id,
            "actor_id": record.actor_id,
            "actor_type": record.actor_type,
            "roles": record.roles,
            "intent": record.intent,
            "request_type": record.request_type,
            "status": record.status,
            "started_at": record.started_at,
            "duration_ms": record.duration_ms,
            "trace_id": record.trace_id,
            "path": record.path,
            "failure_category": record.failure_category,
            "degraded_components": record.degraded_components,
            "recovery_action": record.recovery_action,
            "memory": {
                "item_count": record.memory_item_count,
                "keys": record.memory_keys,
                "types": record.memory_types,
            },
            "tools": record.tools,
            "policy": record.policy,
            "rag_documents": record.rag_documents,
            "retrieval_metadata": record.retrieval_metadata,
            "trace": record.trace,
        }
    )


def _bounded_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_PROJECTION_QUERY_LIMIT)


def _sort_recent(projections: Sequence[AgentRunView], limit: int) -> list[AgentRunView]:
    bounded = _bounded_limit(limit)
    return sorted(
        projections,
        key=lambda projection: (projection.started_at, projection.run_id),
        reverse=True,
    )[:bounded]
