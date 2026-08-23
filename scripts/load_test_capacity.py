"""Run warmup, ramp, sustained, and burst deterministic capacity phases."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.capacity.benchmark import BenchmarkConfig, run_deterministic_benchmark


@dataclass(frozen=True, slots=True)
class Phase:
    name: str
    iterations: int
    workers: int


def run_load_profile(phases: tuple[Phase, ...]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for phase in phases:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=phase.workers) as executor:
            reports = list(
                executor.map(
                    lambda _: run_deterministic_benchmark(
                        BenchmarkConfig(iterations=1, workers=1, warmup=0)
                    ),
                    range(phase.iterations),
                )
            )
        elapsed = time.perf_counter() - started
        results[phase.name] = {
            "requests": len(reports),
            "workers": phase.workers,
            "elapsed_seconds": round(elapsed, 6),
            "throughput_per_second": round(len(reports) / elapsed if elapsed else 0.0, 3),
            "all_invariants_passed": all(all(report.invariants.values()) for report in reports),
        }
    return {"load_profile": "deterministic_capacity_v1", "phases": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sustained-requests", type=int, default=20)
    args = parser.parse_args()
    report = run_load_profile(
        (
            Phase("warmup", 2, 1),
            Phase("ramp_up", 5, 2),
            Phase("sustained", args.sustained_requests, 4),
            Phase("burst", 10, 8),
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(item["all_invariants_passed"] for item in report["phases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
