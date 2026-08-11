import json
from pathlib import Path

from evaluation.metrics.rag import citation_integrity
from evaluation.metrics.safety import confirmation_compliance
from evaluation.metrics.tools import argument_accuracy, selection_accuracy
from evaluation.reporting import compare_reports, render_markdown
from evaluation.runner import fault_scope, load_scenarios, threshold_failure
from evaluation.schemas import EvaluationReport, EvaluationScenario, ScenarioResult


def test_scenario_parser_loads_versioned_dataset() -> None:
    scenarios = load_scenarios(Path("evaluation/datasets"))
    assert len(scenarios) >= 60
    assert {scenario.schema_version for scenario in scenarios} == {"1.0"}
    assert {scenario.category for scenario in scenarios} >= {
        "knowledge",
        "read_action",
        "write_action",
        "confirmation",
        "failure_recovery",
        "prompt_injection",
        "human_escalation",
    }


def test_metric_functions_are_deterministic() -> None:
    assert selection_accuracy(["get_order"], ["get_order"], [])
    assert not selection_accuracy(["cancel_order"], [], ["cancel_order"])
    assert argument_accuracy([{"customer_id": 1, "order_id": 3}], {"order_id": 3})
    assert confirmation_compliance(required=True, pending=True, executed=False, turns=1)
    assert citation_integrity(
        [{"citation_id": "refund-policy#eligibility", "source": "policy.md"}],
        [{"document_id": "refund-policy", "section": "eligibility"}],
    )


def test_fault_scope_restores_tool_definition() -> None:
    scenario = EvaluationScenario.model_validate_json(
        next(
            line
            for line in Path("evaluation/datasets/failure_recovery.jsonl").read_text().splitlines()
            if "failure-004" in line
        )
    )
    from app.agent.tool_catalog import TOOL_DEFINITIONS

    original = TOOL_DEFINITIONS["get_customer_orders"]
    with fault_scope(scenario):
        assert TOOL_DEFINITIONS["get_customer_orders"] != original
    assert TOOL_DEFINITIONS["get_customer_orders"] == original


def test_report_generation_and_comparison() -> None:
    report = EvaluationReport(
        run_id="run",
        seed=0,
        dataset="test",
        started_at="now",
        finished_at="now",
        scenario_count=1,
        results=[],
        metrics={"task_completion_rate": 1.0},
        category_breakdown={},
    )
    assert "Task Completion Rate" in render_markdown(report)
    assert "Baseline" in compare_reports(report, report)
    assert json.loads(report.model_dump_json())["run_id"] == "run"


def test_threshold_failure_rejects_unsafe_report() -> None:
    report = EvaluationReport(
        run_id="run",
        seed=0,
        dataset="test",
        started_at="now",
        finished_at="now",
        scenario_count=1,
        results=[],
        metrics={
            "task_completion_rate": 1.0,
            "tool_selection_accuracy": 1.0,
            "confirmation_compliance": 1.0,
            "unauthorized_action_rate": 0.01,
        },
        category_breakdown={},
    )
    scenario = EvaluationScenario(
        id="critical",
        category="ownership",
        customer_id=1,
        conversation=[{"user": "test"}],
        expect={"critical_safety": True},
    )
    result = ScenarioResult(scenario_id="critical", category="ownership", passed=False)
    assert threshold_failure(report, [scenario], [result])
