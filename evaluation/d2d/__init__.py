"""Executable, non-approving D2d harness components."""

__all__ = ["D2dDryRunRunner"]


def __getattr__(name: str) -> object:
    if name == "D2dDryRunRunner":
        from evaluation.d2d.runner import D2dDryRunRunner

        return D2dDryRunRunner
    raise AttributeError(name)
