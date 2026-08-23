from app.capacity.benchmark import BenchmarkConfig, run_deterministic_benchmark


def test_deterministic_capacity_benchmark_has_expected_workloads() -> None:
    report = run_deterministic_benchmark(BenchmarkConfig(iterations=3, workers=2, warmup=0))

    assert report.provider_calls == 0
    assert set(report.scenarios) == {
        "read_only_customer_inquiry",
        "rag_grounded_response",
        "confirmation_required_operation",
        "successful_write_execution",
        "duplicate_execution_replay",
        "policy_rejection",
    }
    assert all(report.invariants.values())
    assert report.scenarios["rag_grounded_response"].statuses == {"grounded": 3}
    assert report.scenarios["policy_rejection"].statuses == {"denied": 3}
