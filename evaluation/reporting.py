from __future__ import annotations

import json
from pathlib import Path

from evaluation.schemas import EvaluationReport


def write_report(report: EvaluationReport, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.model_dump_json(indent=2) + "\n")
    markdown_path.write_text(render_markdown(report))


def render_markdown(report: EvaluationReport) -> str:
    passed = sum(result.passed for result in report.results)
    lines = [
        "# Agent Evaluation Report",
        "",
        f"- Run: `{report.run_id}`",
        f"- Dataset: `{report.dataset}`",
        f"- Seed: `{report.seed}`",
        f"- Scenarios: {report.scenario_count}",
        f"- Overall pass rate: {passed / report.scenario_count:.1%}",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {key.replace('_', ' ').title()} | {value:.1%} |"
        for key, value in report.metrics.items()
    )
    lines.extend(
        [
            "",
            "## Category breakdown",
            "",
            "| Category | Scenarios | Pass rate |",
            "| --- | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {category} | {int(values['scenarios'])} | {values['pass_rate']:.1%} |"
        for category, values in sorted(report.category_breakdown.items())
    )
    failed = [result for result in report.results if not result.passed]
    lines.extend(["", "## Failed scenarios", ""])
    if not failed:
        lines.append("No failed scenarios.")
    else:
        lines.extend(
            f"- `{result.scenario_id}`: {'; '.join(result.failure_reasons)}" for result in failed
        )
    lines.extend(
        [
            "",
            "## Latency",
            "",
            f"- Mean: {sum(r.latency_ms for r in report.results) / report.scenario_count:.2f} ms",
            f"- Max: {max((r.latency_ms for r in report.results), default=0.0):.2f} ms",
        ]
    )
    return "\n".join(lines) + "\n"


def compare_reports(current: EvaluationReport, baseline: EvaluationReport) -> str:
    lines = [
        f"Baseline `{baseline.run_id}` → current `{current.run_id}`",
        "",
        "| Metric | Baseline | Current | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    keys = sorted(set(baseline.metrics) | set(current.metrics))
    for key in keys:
        before = baseline.metrics.get(key, 0.0)
        after = current.metrics.get(key, 0.0)
        lines.append(
            f"| {key.replace('_', ' ').title()} | {before:.1%} | "
            f"{after:.1%} | {after - before:+.1%} |"
        )
    return "\n".join(lines)


def load_report(path: Path) -> EvaluationReport:
    return EvaluationReport.model_validate(json.loads(path.read_text()))
