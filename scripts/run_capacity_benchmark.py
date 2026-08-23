"""Run the provider-free capacity benchmark and emit a summary only."""

from __future__ import annotations

import argparse
import json

from app.capacity.benchmark import BenchmarkConfig, run_deterministic_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args()
    report = run_deterministic_benchmark(
        BenchmarkConfig(iterations=args.iterations, workers=args.workers, warmup=args.warmup)
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if all(report.invariants.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
