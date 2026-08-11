from __future__ import annotations

from collections.abc import Callable
from contextvars import copy_context
from queue import SimpleQueue
from threading import Thread
from typing import cast


def run_with_timeout[T](operation: Callable[[], T], *, timeout_seconds: float) -> T:
    """Enforce a wall-clock deadline around a synchronous external read boundary."""

    results: SimpleQueue[tuple[bool, object]] = SimpleQueue()
    context = copy_context()

    def invoke() -> None:
        try:
            results.put((True, context.run(operation)))
        except BaseException as error:
            results.put((False, error))

    worker = Thread(target=invoke, name="bounded-external-call", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError("External operation exceeded its configured timeout.")
    succeeded, value = results.get()
    if not succeeded:
        raise cast(BaseException, value)
    return cast(T, value)
