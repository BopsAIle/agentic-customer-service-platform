"""D2d dry-run and prospective release-gate components."""

__all__ = ["D2dDryRunRunner", "D2dReleaseRunner"]


def __getattr__(name: str) -> object:
    if name == "D2dDryRunRunner":
        from evaluation.d2d.runner import D2dDryRunRunner

        return D2dDryRunRunner
    if name == "D2dReleaseRunner":
        from evaluation.d2d.release_runner import D2dReleaseRunner

        return D2dReleaseRunner
    raise AttributeError(name)
