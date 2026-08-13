"""Allow-listed, privacy-safe provenance for live benchmark artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from app.agent.schemas import StructuredDecision

PROVENANCE_VERSION = "benchmark_provenance_v1"
DECISION_CONTRACT_VERSION = "direct_tool_v1"


class Provenance(BaseModel):
    version: str = PROVENANCE_VERSION
    model: dict[str, Any]
    runtime: dict[str, Any]
    hardware: dict[str, Any]
    decision_contract: dict[str, Any]
    benchmark: dict[str, Any]
    usage: dict[str, Any]


def canonical_schema_hash(schema: dict[str, Any]) -> str:
    payload = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def direct_tool_schema_hash() -> str:
    return canonical_schema_hash(StructuredDecision.model_json_schema())


def git_metadata(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    try:
        revision = runner(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = bool(
            runner(
                ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
            ).stdout.strip()
        )
        return {"source_revision": revision or None, "dirty_worktree": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"source_revision": None, "dirty_worktree": None}


def _hardware_metadata(
    *,
    system: Callable[[], str] = platform.system,
    release: Callable[[], str] = platform.release,
    machine: Callable[[], str] = platform.machine,
    processor: Callable[[], str] = platform.processor,
    environ: dict[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    values = environ if environ is not None else os.environ
    memory: int | None = None
    machine_identifier: str | None = None
    if system() == "Darwin":
        try:
            machine_identifier = (
                runner(
                    ["sysctl", "-n", "hw.model"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                or None
            )
            memory = int(
                runner(
                    ["sysctl", "-n", "hw.memsize"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
        except (OSError, ValueError, subprocess.CalledProcessError):
            memory = None
    elif system() == "Linux":
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    memory = int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError, IndexError):
            memory = None
    return {
        "machine": machine_identifier,
        "os": f"{system()} {release()}".strip() or None,
        "architecture": machine() or None,
        "cpu": processor() or None,
        "accelerator": None,
        "memory_bytes": memory,
        "collection_note": (
            "Privacy-safe; hostname, username, serials, UUIDs, MACs and IPs excluded."
        ),
        "environment_used": "none" if not values else "allowlisted-only",
    }


def _runtime(
    args: Any, *, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> dict[str, Any]:
    base_url = str(args.base_url)
    hostname = (urlparse(base_url).hostname or "").casefold()
    local = hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    runtime_name = "Ollama" if local else "OpenAI-compatible service"
    runtime_version: str | None = None
    if local:
        try:
            result = runner(["ollama", "version"], check=True, capture_output=True, text=True)
            runtime_version = result.stdout.strip() or result.stderr.strip() or None
        except (OSError, subprocess.CalledProcessError):
            runtime_version = None
    return {
        "runtime_name": runtime_name,
        "runtime_version": runtime_version,
        "transport": "openai_compatible_chat_completions",
        "structured_output_mode": getattr(args, "structured_output_mode", "schema"),
        "reasoning_effort": getattr(args, "reasoning_effort", None),
        "temperature": getattr(args, "temperature", None),
        "timeout_seconds": getattr(args, "timeout", None),
        "retry_policy": {"sdk_max_retries": 0, "application_retry_attempts": 0},
        "configured_context_window": None,
        "model_reported_context_window": None,
    }


def build_provenance(
    *,
    args: Any,
    case_set_version: str,
    case_set_hash: str,
    prompt_hash: str,
    scoring_version: str,
    runs_per_case: int,
    unique_cases: int,
    total_attempts: int,
    usage: dict[str, Any] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    usage_data = {
        "usage_available": False,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost": None,
        "cost_status": "not_applicable"
        if (urlparse(str(args.base_url)).hostname or "").casefold()
        in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        else "unavailable",
        "cost_currency": None,
    }
    if usage:
        usage_data.update(usage)
    git = git_metadata(runner)
    return Provenance(
        model={
            "provider": "openai_compatible",
            "model_name": args.model,
            "exact_model_identifier": args.model,
            "model_digest": None,
            "quantization": None,
            "parameter_count": None,
            "parameter_count_label": None,
        },
        runtime=_runtime(args, runner=runner),
        hardware=_hardware_metadata(runner=runner),
        decision_contract={
            "version": DECISION_CONTRACT_VERSION,
            "schema_hash": direct_tool_schema_hash(),
        },
        benchmark={
            "case_set_version": case_set_version,
            "case_set_hash": case_set_hash,
            "prompt_hash": prompt_hash,
            "scoring_version": scoring_version,
            "source_revision": git["source_revision"],
            "dirty_worktree": git["dirty_worktree"],
            "runs_per_case": runs_per_case,
            "unique_cases": unique_cases,
            "total_attempts": total_attempts,
        },
        usage=usage_data,
    ).model_dump(mode="json")


def validate_provenance(provenance: dict[str, Any]) -> None:
    required = {
        "version",
        "model",
        "runtime",
        "hardware",
        "decision_contract",
        "benchmark",
        "usage",
    }
    missing = required - provenance.keys()
    if missing:
        raise ValueError(f"missing provenance fields: {sorted(missing)}")
    for section, fields in {
        "model": ("provider", "model_name"),
        "runtime": ("transport", "structured_output_mode", "reasoning_effort", "timeout_seconds"),
        "decision_contract": ("version", "schema_hash"),
        "benchmark": (
            "case_set_version",
            "case_set_hash",
            "prompt_hash",
            "scoring_version",
            "source_revision",
            "runs_per_case",
        ),
    }.items():
        absent = [field for field in fields if field not in provenance[section]]
        if absent:
            raise ValueError(f"missing provenance {section} fields: {absent}")
    if provenance["decision_contract"]["version"] != DECISION_CONTRACT_VERSION:
        raise ValueError("unsupported decision contract")
    if provenance["decision_contract"]["schema_hash"] != direct_tool_schema_hash():
        raise ValueError("decision contract schema hash mismatch")


def historical_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    """Project only evidence present in a legacy artifact; unknowns stay null."""

    local = metadata.get("base_url_classification") == "local"
    return Provenance(
        model={
            "provider": metadata.get("provider"),
            "model_name": metadata.get("model"),
            "exact_model_identifier": None,
            "model_digest": None,
            "quantization": None,
            "parameter_count": None,
            "parameter_count_label": None,
        },
        runtime={
            "runtime_name": "Ollama" if local else None,
            "runtime_version": None,
            "transport": "openai_compatible_chat_completions",
            "structured_output_mode": metadata.get("structured_output_mode"),
            "reasoning_effort": metadata.get("reasoning_effort"),
            "temperature": metadata.get("temperature"),
            "timeout_seconds": metadata.get("timeout_seconds"),
            "retry_policy": {"sdk_max_retries": None, "application_retry_attempts": None},
            "configured_context_window": None,
            "model_reported_context_window": None,
        },
        hardware={
            "machine": None,
            "os": None,
            "architecture": None,
            "cpu": None,
            "accelerator": None,
            "memory_bytes": None,
            "collection_note": "Unavailable in the frozen source artifact.",
        },
        decision_contract={
            "version": DECISION_CONTRACT_VERSION,
            "schema_hash": direct_tool_schema_hash(),
        },
        benchmark={
            "case_set_version": metadata.get("case_set_version"),
            "case_set_hash": metadata.get("case_set_sha256"),
            "prompt_hash": metadata.get("prompt_hash"),
            "scoring_version": metadata.get("scoring_version"),
            "source_revision": metadata.get("source_revision"),
            "dirty_worktree": None,
            "runs_per_case": metadata.get("runs_per_case"),
            "unique_cases": metadata.get("case_count"),
            "total_attempts": metadata.get("attempts"),
        },
        usage={
            "usage_available": bool(metadata.get("usage_available", False)),
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost": None,
            "cost_status": "not_applicable" if local else "unavailable",
            "cost_currency": None,
        },
    ).model_dump(mode="json")
