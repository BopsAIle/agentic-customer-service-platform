"""OpenAI structured-output compatibility control for semantic_decision_v2."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.agent.llm.provider import OpenAICompatibleProvider
from evaluation.provenance import (
    build_provenance,
    prompt_hash_for_contract,
    schema_hash_for_contract,
)
from evaluation.structured_output_diagnostics import (
    CONTRACT_VERSION,
    DIAGNOSTIC_CASE_IDS,
    RUNS_PER_CASE,
    DiagnosticArtifact,
    _case_map,
    _counts,
    _markdown,
    _run_attempt,
)

OPENAI_BASE_URL = "https://api.openai.com/v1"
LUNA_ID_FRAGMENT = "gpt-5.6-luna"
MAX_GENERATION_CALLS = 25
MEASURED_ATTEMPTS = len(DIAGNOSTIC_CASE_IDS) * RUNS_PER_CASE


class GenerationCallBudget:
    def __init__(self, maximum: int = MAX_GENERATION_CALLS) -> None:
        self.maximum = maximum
        self.calls = 0

    def consume(self) -> None:
        if self.calls >= self.maximum:
            raise RuntimeError("generation call budget exceeded")
        self.calls += 1


class CountingProvider:
    def __init__(self, provider: OpenAICompatibleProvider, budget: GenerationCallBudget) -> None:
        self.provider = provider
        self.budget = budget

    @property
    def last_validation_diagnostic(self) -> Any:
        return self.provider.last_validation_diagnostic

    @property
    def last_structured_call_metadata(self) -> Any:
        return self.provider.last_structured_call_metadata

    def decide(self, **kwargs: Any) -> Any:
        self.budget.consume()
        return self.provider.decide(**kwargs)


def select_luna_model(model_ids: Iterable[str]) -> str:
    matches = sorted(
        {model_id for model_id in model_ids if LUNA_ID_FRAGMENT in model_id.casefold()}
    )
    if not matches:
        raise RuntimeError("OPENAI_LUNA_NOT_AVAILABLE")
    if len(matches) != 1:
        raise RuntimeError("OPENAI_LUNA_MODEL_AMBIGUOUS")
    return matches[0]


def list_openai_model_ids(api_key: str) -> list[str]:
    client = OpenAI(api_key=api_key, base_url=OPENAI_BASE_URL)
    return [str(model.id) for model in client.models.list().data]


def control_configuration(model_id: str) -> dict[str, Any]:
    return {
        "provider": "openai",
        "runtime": "OpenAI API",
        "endpoint": OPENAI_BASE_URL,
        "model_id": model_id,
        "decision_contract_version": CONTRACT_VERSION,
        "schema_hash": schema_hash_for_contract(CONTRACT_VERSION),
        "prompt_hash": prompt_hash_for_contract(CONTRACT_VERSION),
        "structured_output_mode": "function_calling",
        "reasoning_effort": "none",
        "temperature": 0.0,
        "timeout_seconds": 30.0,
        "retry_policy": {"sdk_max_retries": 0, "application_retry_attempts": 0},
        "runs_per_case": RUNS_PER_CASE,
        "measured_attempts": MEASURED_ATTEMPTS,
        "maximum_generation_calls": MAX_GENERATION_CALLS,
    }


def _warmup(provider: CountingProvider, case_id: str) -> tuple[bool, str | None]:
    case = _case_map()[case_id]
    try:
        provider.decide(
            messages=[{"role": "user", "content": case.rendered_input()}],
            customer_id=case.customer_id,
        )
    except Exception as error:
        return False, type(error).__name__
    return True, None


def _failure_code(error_type: str | None) -> str:
    if error_type is None:
        return "OPENAI_CONTROL_WARMUP_FAILED"
    lowered = error_type.casefold()
    if "reason" in lowered:
        return "REASONING_CONFIGURATION_NOT_COMPARABLE"
    if "temper" in lowered:
        return "TEMPERATURE_CONFIGURATION_NOT_COMPARABLE"
    return "OPENAI_CONTROL_WARMUP_FAILED"


def run_control(
    *,
    diagnostic_id: str,
    output_dir: Path,
    api_key: str,
    model_id: str,
) -> DiagnosticArtifact:
    configuration = control_configuration(model_id)
    settings = argparse.Namespace(
        model=model_id,
        base_url=OPENAI_BASE_URL,
        api_key=api_key,
        temperature=0.0,
        reasoning_effort="none",
        structured_output_mode="function_calling",
        decision_contract_version=CONTRACT_VERSION,
        connect_timeout=5.0,
        timeout=30.0,
    )
    provider = OpenAICompatibleProvider(
        __import__("app.core.config", fromlist=["Settings"]).Settings(
            _env_file=None,
            app_env="development",
            llm_provider="openai_compatible",
            llm_model=model_id,
            llm_base_url=OPENAI_BASE_URL,
            llm_api_key=api_key,
            llm_temperature=0.0,
            llm_reasoning_effort="none",
            llm_structured_output_mode="function_calling",
            agent_decision_contract_version=CONTRACT_VERSION,
            llm_connect_timeout_seconds=5.0,
            llm_timeout_seconds=30.0,
            checkpoint_backend="memory",
            policy_audit_backend="memory",
            agent_run_projection_backend="memory",
            rag_backend="local",
            memory_enabled=False,
        )
    )
    budget = GenerationCallBudget()
    counted = CountingProvider(provider, budget)
    warmup_success, warmup_error_type = _warmup(counted, DIAGNOSTIC_CASE_IDS[0])
    if not warmup_success:
        raise RuntimeError(_failure_code(warmup_error_type))
    cases = _case_map()
    attempts = []
    for case_id in DIAGNOSTIC_CASE_IDS:
        for run_index in range(1, RUNS_PER_CASE + 1):
            attempt = _run_attempt(counted, cases[case_id], run_index)
            attempts.append(attempt)
    if budget.calls != MAX_GENERATION_CALLS:
        raise RuntimeError("OPENAI_CONTROL_CALL_BUDGET_INCOMPLETE")
    case_metadata = {
        "version": "live_eval_v1",
        "sha256": "888e8ed77435d8eb864ae01784852798c17e0f1829400296ba78305b3b95d6ae",
    }
    provenance = build_provenance(
        args=settings,
        case_set_version=case_metadata["version"],
        case_set_hash=case_metadata["sha256"],
        prompt_hash=configuration["prompt_hash"],
        scoring_version="structured_output_diagnostic_v1",
        runs_per_case=RUNS_PER_CASE,
        unique_cases=len(DIAGNOSTIC_CASE_IDS),
        total_attempts=len(attempts),
        decision_contract_version=CONTRACT_VERSION,
    )
    provenance["model"].update(
        {
            "provider": "openai",
            "model_name": model_id,
            "exact_model_identifier": model_id,
            "model_digest": None,
            "quantization": None,
            "inference_hardware": "provider_managed",
        }
    )
    provenance["runtime"].update(
        {
            "runtime_name": "OpenAI API",
            "runtime_version": None,
            "endpoint_classification": "official_openai_api",
            "transport": "openai_compatible_chat_completions",
        }
    )
    experiment = {
        **configuration,
        "contract_version": CONTRACT_VERSION,
        "diagnostic_schema_version": "structured_output_diagnostic_v1",
        "diagnostic_id": diagnostic_id,
        "base_product_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "diagnostic_harness_source_state": "clean_committed_harness",
        "selected_case_ids": list(DIAGNOSTIC_CASE_IDS),
        "warmup_performed": True,
        "warmup_success": warmup_success,
        "measured_attempts": len(attempts),
        "total_generation_calls": budget.calls,
        "invalidated_attempts": [],
        "usage_available": False,
        "cost": None,
        "cost_status": "unavailable",
        "api_key_persisted": False,
        "no_raw_values_persisted": True,
    }
    artifact = DiagnosticArtifact(
        diagnostic_id=diagnostic_id,
        experiment=experiment,
        provenance=provenance,
        transport_schema=provider.structured_schema_metadata(),
        attempts=attempts,
        summary=_counts(attempts),
    )
    destination = output_dir / diagnostic_id
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "attempts.json").write_text(
        artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (destination / "summary.json").write_text(
        json.dumps(artifact.summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "summary.md").write_text(_markdown(artifact), encoding="utf-8")
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAI structured-output compatibility control")
    parser.add_argument("--diagnostic-id", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/live-eval/structured-output-diagnostics"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    model_id = select_luna_model(list_openai_model_ids(api_key))
    artifact = run_control(
        diagnostic_id=args.diagnostic_id,
        output_dir=args.output_dir,
        api_key=api_key,
        model_id=model_id,
    )
    print(f"selected_model_id={model_id}")
    print(f"diagnostic_id={artifact.diagnostic_id}")
    print(f"generation_calls={artifact.experiment['total_generation_calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
