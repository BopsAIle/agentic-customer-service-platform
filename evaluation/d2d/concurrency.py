"""Deterministic concurrency helpers with no retry or result suppression."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class ConcurrentResult[T]:
    ordinal: int
    started: bool
    start_time: float | None
    end_time: float | None
    value: T | None
    error_type: str | None


def run_overlapping[T](
    workers: int,
    operation: Callable[[int, threading.Barrier], T],
) -> tuple[ConcurrentResult[T], ...]:
    """Run exactly ``workers`` operations behind one start barrier.

    Exceptions are returned as bounded result data. There is deliberately no retry path and no
    early cancellation: every submitted worker must be accounted for.
    """

    if workers < 1:
        raise ValueError("workers must be positive")
    barrier = threading.Barrier(workers)
    results: list[ConcurrentResult[T] | None] = [None] * workers

    def invoke(ordinal: int) -> None:
        started_at: float | None = None
        try:
            barrier.wait(timeout=30)
            started_at = time.monotonic()
            value = operation(ordinal, barrier)
            results[ordinal] = ConcurrentResult(
                ordinal=ordinal,
                started=True,
                start_time=started_at,
                end_time=time.monotonic(),
                value=value,
                error_type=None,
            )
        except Exception as error:  # noqa: BLE001 - retained as bounded worker evidence
            results[ordinal] = ConcurrentResult(
                ordinal=ordinal,
                started=started_at is not None,
                start_time=started_at,
                end_time=time.monotonic() if started_at is not None else None,
                value=None,
                error_type=type(error).__name__,
            )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="d2d") as pool:
        futures: Sequence[Future[None]] = tuple(
            pool.submit(invoke, ordinal) for ordinal in range(workers)
        )
        for future in futures:
            future.result()
    if any(result is None for result in results):
        raise RuntimeError("D2D_CONCURRENCY_RESULT_MISSING")
    return tuple(result for result in results if result is not None)
