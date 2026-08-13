"""Targeted, privacy-safe structured-output reliability diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.llm.diagnostics import (
    DIAGNOSTIC_SCHEMA_VERSION,
    StructuredDecisionValidationDiagnostic,
    ValidationStage,
    from_exception,
)
from app.agent.schemas import SemanticDecision
from evaluation.architecture_ab import _model_metadata
from evaluation.live import _base_url_classification, _preflight, _provider, _warmup
from evaluation.live_cases import LIVE_CASE_SET_VERSION, LiveEvalCase, live_cases
from evaluation.live_scoring import case_set_metadata
from evaluation.provenance import build_provenance, prompt_hash_for_contract

CONTRACT_VERSION = "semantic_decision_v2"
MODEL = "qwen3.5:4b"
RUNS_PER_CASE = 3
DIAGNOSTIC_CASE_IDS = (
    "en-clarify-order",
    "en-fake-id",
    "en-ticket-damaged",
    "tr-ticket-damaged",
    "tr-refund-damaged",
    "tr-cancel-no-id",
    "tr-cancel-no-confirmation",
    "tr-prompt-injection",
)
HISTORICAL_FAILURES = {case_id: "3/3" for case_id in DIAGNOSTIC_CASE_IDS}


class DiagnosticAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    language: str
    category: str
    run_index: int
    contract_version: str
    provider_success: bool
    typed_decision_success: bool
    structured_call_present: bool | None = None
    tool_call_count: int | None = None
    function_name_present: bool | None = None
    arguments_present: bool | None = None
    arguments_decoded: bool | None = None
    typed_model_constructed: bool = False
    target_variant: str | None = None
    target_keys: list[str] = Field(default_factory=list)
    target_identifier_json_type: str | None = None
    validation_stage: str | None = None
    validation_diagnostic: StructuredDecisionValidationDiagnostic | None = None
    error_type: str | None = None
    latency_ms: float = Field(ge=0.0)


class DiagnosticArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = DIAGNOSTIC_SCHEMA_VERSION
    artifact_type: str = "structured_output_diagnostic_attempts"
    diagnostic_id: str
    experiment: dict[str, Any]
    provenance: dict[str, Any]
    transport_schema: dict[str, Any]
    attempts: list[DiagnosticAttempt]
    summary: dict[str, Any]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _counts(attempts: list[DiagnosticAttempt]) -> dict[str, Any]:
    failures = [item for item in attempts if not item.typed_decision_success]
    error_types = Counter(
        error.type
        for item in failures
        if item.validation_diagnostic
        for error in item.validation_diagnostic.errors
    )
    locations = Counter(
        error.location
        for item in failures
        if item.validation_diagnostic
        for error in item.validation_diagnostic.errors
    )
    stages = Counter(item.validation_stage for item in failures if item.validation_stage)
    signatures = Counter(
        "+".join(f"{error.type}@{error.location}" for error in diagnostic.errors)
        for item in failures
        if (diagnostic := item.validation_diagnostic) is not None
    )
    latencies = [item.latency_ms for item in attempts]
    return {
        "attempts": len(attempts),
        "provider_success": sum(item.provider_success for item in attempts),
        "typed_decision_success": sum(item.typed_decision_success for item in attempts),
        "validation_failures": len(failures),
        "by_error_type": dict(sorted(error_types.items())),
        "by_field_location": dict(sorted(locations.items())),
        "by_validation_stage": dict(sorted(stages.items())),
        "common_error_signatures": [
            {"signature": signature, "count": count}
            for signature, count in signatures.most_common()
        ],
        "by_language": {
            language: _counts([item for item in attempts if item.language == language])
            for language in ("en", "tr")
        }
        if attempts and len({item.language for item in attempts}) > 1
        else {},
        "by_case": {
            case_id: {
                "attempts": len(case_attempts),
                "typed_decision_success": sum(
                    item.typed_decision_success for item in case_attempts
                ),
                "validation_failures": sum(
                    not item.typed_decision_success for item in case_attempts
                ),
                "historical_d1_failure_rate": HISTORICAL_FAILURES.get(case_id),
            }
            for case_id in DIAGNOSTIC_CASE_IDS
            if (case_attempts := [item for item in attempts if item.case_id == case_id])
        },
        "by_capability": {
            category: {
                "attempts": len(category_attempts),
                "typed_decision_success": sum(
                    item.typed_decision_success for item in category_attempts
                ),
                "validation_failures": sum(
                    not item.typed_decision_success for item in category_attempts
                ),
            }
            for category in sorted({item.category for item in attempts})
            if (category_attempts := [item for item in attempts if item.category == category])
        },
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
    }


def _case_map() -> dict[str, LiveEvalCase]:
    cases = {case.id: case for case in live_cases()}
    missing = [case_id for case_id in DIAGNOSTIC_CASE_IDS if case_id not in cases]
    if missing:
        raise SystemExit(f"Frozen diagnostic cases missing: {', '.join(missing)}")
    return cases


def _run_attempt(
    provider: Any,
    case: LiveEvalCase,
    run_index: int,
    *,
    contract_version: str = CONTRACT_VERSION,
    expected_decision_type: type[BaseModel] = SemanticDecision,
) -> DiagnosticAttempt:
    started = time.perf_counter()
    provider_success = False
    typed_success = False
    diagnostic: StructuredDecisionValidationDiagnostic | None = None
    error_type: str | None = None
    try:
        proposal = provider.decide(
            messages=[{"role": "user", "content": case.rendered_input()}],
            customer_id=case.customer_id,
        )
        provider_success = True
        typed_success = isinstance(proposal, expected_decision_type)
        if not typed_success:
            diagnostic = from_exception(
                TypeError("unexpected decision contract"),
                contract_version=contract_version,
                stage=ValidationStage.POST_VALIDATION_FAILURE,
                validation_layer="contract_dispatch",
                provider_success=True,
                structured_call_present=True,
                argument_payload_kind=type(proposal).__name__,
            )
            error_type = type(proposal).__name__
    except ValidationError as error:
        provider_success = True
        diagnostic = provider.last_validation_diagnostic
        error_type = type(error).__name__
    except Exception as error:
        diagnostic = provider.last_validation_diagnostic
        provider_success = bool(diagnostic and diagnostic.provider_success)
        error_type = type(error).__name__
    metadata = provider.last_structured_call_metadata
    if diagnostic is not None:
        metadata = {
            "structured_call_present": diagnostic.structured_call_present,
            "tool_call_count": diagnostic.tool_call_count,
            "function_name_present": diagnostic.function_name_present,
            "arguments_present": diagnostic.arguments_present,
            "arguments_decoded": diagnostic.arguments_decoded,
            "argument_payload_kind": diagnostic.argument_payload_kind,
            "target_variant": diagnostic.target_variant,
            "target_keys": diagnostic.observed_target_keys,
            "target_identifier_json_type": diagnostic.target_identifier_json_type,
        }
    latency_ms = (time.perf_counter() - started) * 1000
    return DiagnosticAttempt(
        case_id=case.id,
        language=case.language,
        category=case.category,
        run_index=run_index,
        contract_version=contract_version,
        provider_success=provider_success,
        typed_decision_success=typed_success,
        structured_call_present=metadata.get("structured_call_present"),
        tool_call_count=metadata.get("tool_call_count"),
        function_name_present=metadata.get("function_name_present"),
        arguments_present=metadata.get("arguments_present"),
        arguments_decoded=metadata.get("arguments_decoded"),
        typed_model_constructed=typed_success,
        target_variant=metadata.get("target_variant"),
        target_keys=metadata.get("target_keys", []),
        target_identifier_json_type=metadata.get("target_identifier_json_type"),
        validation_stage=diagnostic.stage.value if diagnostic else None,
        validation_diagnostic=diagnostic,
        error_type=error_type,
        latency_ms=latency_ms,
    )


def _markdown(artifact: DiagnosticArtifact) -> str:
    summary = artifact.summary
    lines = [
        "# Structured Output Diagnostic Report",
        "",
        f"- Diagnostic: `{artifact.diagnostic_id}`",
        f"- Contract: `{artifact.experiment['contract_version']}`",
        f"- Attempts: `{summary['attempts']}`",
        f"- Typed decisions: `{summary['typed_decision_success']}`",
        f"- Validation failures: `{summary['validation_failures']}`",
        "",
        "## Error Types",
        "",
        "```json",
        json.dumps(summary["by_error_type"], indent=2, ensure_ascii=False),
        "```",
        "",
        "## Field Locations",
        "",
        "```json",
        json.dumps(summary["by_field_location"], indent=2, ensure_ascii=False),
        "```",
        "",
        "## Historical Comparison",
        "",
        "```json",
        json.dumps(summary["by_case"], indent=2, ensure_ascii=False),
        "```",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    if args.runs_per_case != RUNS_PER_CASE:
        raise SystemExit("Structured diagnostics require exactly 3 runs per case")
    case_by_id = _case_map()
    cases = [case_by_id[case_id] for case_id in DIAGNOSTIC_CASE_IDS]
    case_metadata = case_set_metadata(live_cases())
    _preflight(args)
    provider = _provider(args)
    warmup_performed = True
    warmup_error: str | None = None
    try:
        _warmup(provider, cases[0].customer_id)
    except Exception as error:
        warmup_error = type(error).__name__
    print(
        f"Warmup complete; measured cases={len(cases)} runs_per_case={args.runs_per_case}",
        flush=True,
    )
    attempts: list[DiagnosticAttempt] = []
    for case in cases:
        for run_index in range(1, args.runs_per_case + 1):
            attempt = _run_attempt(provider, case, run_index)
            attempts.append(attempt)
            print(
                f"{case.id} run={run_index} typed={attempt.typed_decision_success} "
                f"stage={attempt.validation_stage or 'none'} "
                f"latency_ms={attempt.latency_ms:.1f}",
                flush=True,
            )
    diagnostic_id = args.diagnostic_id or (
        f"structured_output_qwen3_5_4b_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    )
    schema_metadata = provider.structured_schema_metadata()
    provenance = build_provenance(
        args=args,
        case_set_version=LIVE_CASE_SET_VERSION,
        case_set_hash=str(case_metadata["sha256"]),
        prompt_hash=prompt_hash_for_contract(CONTRACT_VERSION),
        scoring_version=DIAGNOSTIC_SCHEMA_VERSION,
        runs_per_case=args.runs_per_case,
        unique_cases=len(cases),
        total_attempts=len(attempts),
        decision_contract_version=CONTRACT_VERSION,
    )
    model_metadata = _model_metadata(args.base_url, args.model)
    provenance["model"].update(model_metadata)
    experiment = {
        "version": DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_id": diagnostic_id,
        "contract_version": CONTRACT_VERSION,
        "selected_case_ids": list(DIAGNOSTIC_CASE_IDS),
        "case_set_version": LIVE_CASE_SET_VERSION,
        "case_set_sha256": case_metadata["sha256"],
        "base_product_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "diagnostic_source_state": "dirty_uncommitted_instrumentation",
        "warmup_performed": warmup_performed,
        "warmup_error_type": warmup_error,
        "measured_attempts": len(attempts),
        "invalidated_attempts": [],
        "no_raw_values_persisted": True,
        "structured_output_mode": args.structured_output_mode,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "temperature": args.temperature,
        "timeout_seconds": args.timeout,
        "retry_policy": {"sdk_max_retries": 0, "application_retry_attempts": 0},
        "base_url_classification": _base_url_classification(args.base_url),
    }
    artifact = DiagnosticArtifact(
        diagnostic_id=diagnostic_id,
        experiment=experiment,
        provenance=provenance,
        transport_schema=schema_metadata,
        attempts=attempts,
        summary=_counts(attempts),
    )
    output_dir = args.output_dir / diagnostic_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "attempts.json").write_text(
        artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(artifact.summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(_markdown(artifact), encoding="utf-8")
    print(f"Diagnostic artifact: {output_dir}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Targeted structured-output diagnostics")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--api-key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--runs-per-case", type=int, default=RUNS_PER_CASE)
    parser.add_argument("--diagnostic-id")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--reasoning-effort", default="none")
    parser.add_argument("--structured-output-mode", default="function_calling")
    parser.add_argument("--decision-contract-version", default=CONTRACT_VERSION)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(_parser().parse_args(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
