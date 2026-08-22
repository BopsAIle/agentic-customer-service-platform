"""Small, deterministic fault-controller primitives for the D2d harness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal


class FaultControllerError(RuntimeError):
    """A fault could not be activated, restored, or used safely."""


class FaultController:
    """Activate one fault and guarantee an explicit restoration attempt.

    The controller intentionally has no retry behavior.  A restoration failure is surfaced as a
    harness/environment failure rather than allowing a later scenario to run in a contaminated
    environment.
    """

    def __init__(
        self,
        fault_id: str,
        activate: Callable[[], None],
        restore: Callable[[], None],
    ) -> None:
        self.fault_id = fault_id
        self._activate = activate
        self._restore = restore
        self.active = False

    def __enter__(self) -> FaultController:
        try:
            self._activate()
        except Exception as error:
            raise FaultControllerError(f"D2D_FAULT_ACTIVATION_FAILED:{self.fault_id}") from error
        self.active = True
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> Literal[False]:
        if not self.active:
            return False
        try:
            self._restore()
        except Exception as error:
            raise FaultControllerError(f"D2D_FAULT_RESTORE_FAILED:{self.fault_id}") from error
        finally:
            self.active = False
        return False
