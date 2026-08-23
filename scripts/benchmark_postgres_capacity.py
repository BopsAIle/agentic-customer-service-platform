"""Benchmark isolated persistence primitives against SQLite or PostgreSQL.

Set ``CAPACITY_DATABASE_URL`` to a dedicated PostgreSQL benchmark database to
measure PostgreSQL.  Without it, a temporary SQLite database is used so CI and
local development remain provider-free and side-effect limited.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def run_database_benchmark(*, operations: int = 100, workers: int = 8) -> dict[str, Any]:
    if operations <= 0 or workers <= 0:
        raise ValueError("operations and workers must be positive")
    temporary_path: Path | None = None
    database_url = os.getenv("CAPACITY_DATABASE_URL")
    if not database_url:
        temporary_path = Path(tempfile.gettempdir()) / f"capacity-benchmark-{uuid4().hex}.sqlite"
        database_url = f"sqlite:///{temporary_path}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    _create_table(engine)
    try:
        same_key = _run_same_key(engine, workers)
        different_keys = _run_different_keys(engine, operations, workers)
        return {
            "benchmark": "isolated_persistence_capacity_v1",
            "database_backend": "postgresql" if database_url.startswith("postgres") else "sqlite",
            "operations": operations,
            "workers": workers,
            "same_idempotency_key": same_key,
            "different_idempotency_keys": different_keys,
            "privacy": {
                "raw_user_content": False,
                "secrets": False,
                "provider_calls": 0,
            },
        }
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE capacity_benchmark_effects"))
        engine.dispose()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _create_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE capacity_benchmark_effects ("
                "tenant_id VARCHAR(200) NOT NULL, "
                "operation_key VARCHAR(200) NOT NULL, "
                "created_at VARCHAR(40) NOT NULL, "
                "PRIMARY KEY (tenant_id, operation_key)"
                ")"
            )
        )


def _insert(engine: Engine, tenant_id: str, operation_key: str) -> tuple[str, float]:
    started = time.perf_counter()
    if engine.url.get_backend_name() == "sqlite":
        statement = text(
            "INSERT OR IGNORE INTO capacity_benchmark_effects "
            "(tenant_id, operation_key, created_at) VALUES "
            "(:tenant_id, :operation_key, :created_at)"
        )
    else:
        statement = text(
            "INSERT INTO capacity_benchmark_effects "
            "(tenant_id, operation_key, created_at) VALUES "
            "(:tenant_id, :operation_key, :created_at) "
            "ON CONFLICT (tenant_id, operation_key) DO NOTHING"
        )
    with engine.begin() as connection:
        result = connection.execute(
            statement,
            {"tenant_id": tenant_id, "operation_key": operation_key, "created_at": "bounded"},
        )
    return "committed" if result.rowcount else "idempotent_replay", time.perf_counter() - started


def _run_same_key(engine: Engine, workers: int) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        values = list(
            executor.map(lambda _: _insert(engine, "tenant-a", "same-key"), range(workers))
        )
    with engine.connect() as connection:
        count = int(
            connection.scalar(
                text(
                    "SELECT COUNT(*) FROM capacity_benchmark_effects "
                    "WHERE tenant_id = 'tenant-a' AND operation_key = 'same-key'"
                )
            )
        )
    return {
        "attempts": workers,
        "business_effects": count,
        "one_effect": count == 1,
        "status_counts": _status_counts(values),
        "latency_ms": _latency_summary(values),
    }


def _run_different_keys(engine: Engine, operations: int, workers: int) -> dict[str, Any]:
    keys = [(f"tenant-{index % 2}", f"key-{index}") for index in range(operations)]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        values = list(executor.map(lambda item: _insert(engine, *item), keys))
    with engine.connect() as connection:
        count = int(connection.scalar(text("SELECT COUNT(*) FROM capacity_benchmark_effects")))
    return {
        "attempts": operations,
        "business_effects": count,
        "independent_effects": count == operations + 1,
        "status_counts": _status_counts(values),
        "latency_ms": _latency_summary(values),
    }


def _status_counts(values: list[tuple[str, float]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status, _ in values:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _latency_summary(values: list[tuple[str, float]]) -> dict[str, float]:
    samples = sorted(value for _, value in values)
    return {
        "p50": round(_percentile(samples, 0.50) * 1000, 3),
        "p95": round(_percentile(samples, 0.95) * 1000, 3),
        "p99": round(_percentile(samples, 0.99) * 1000, 3),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(quantile * 100) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    result = run_database_benchmark(operations=args.operations, workers=args.workers)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["same_idempotency_key"]["one_effect"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
