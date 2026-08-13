from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.schemas import StructuredDecision
from evaluation.provenance import (
    DECISION_CONTRACT_VERSION,
    _hardware_metadata,
    build_provenance,
    canonical_schema_hash,
    direct_tool_schema_hash,
    git_metadata,
    validate_provenance,
)


def _result(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["test"], 0, stdout, stderr)


def _args(**overrides: object) -> SimpleNamespace:
    values = {
        "model": "qwen3.5:9b",
        "base_url": "http://localhost:11434/v1",
        "structured_output_mode": "function_calling",
        "reasoning_effort": "none",
        "temperature": 0.0,
        "timeout": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_schema_hash_is_canonical_and_changes_for_meaningful_change() -> None:
    schema = StructuredDecision.model_json_schema()
    reordered = {key: schema[key] for key in reversed(list(schema))}
    assert canonical_schema_hash(schema) == canonical_schema_hash(reordered)
    changed = dict(schema)
    changed["title"] = "DifferentDecision"
    assert canonical_schema_hash(schema) != canonical_schema_hash(changed)
    assert len(direct_tool_schema_hash()) == 64


def test_provenance_captures_contract_transport_and_nullable_reasoning() -> None:
    provenance = build_provenance(
        args=_args(),
        case_set_version="live_eval_v1",
        case_set_hash="c" * 64,
        prompt_hash="p" * 64,
        scoring_version="live_scoring_v3",
        runs_per_case=3,
        unique_cases=28,
        total_attempts=84,
        runner=lambda *args, **kwargs: _result(""),
    )
    assert provenance["version"] == "benchmark_provenance_v1"
    assert provenance["decision_contract"]["version"] == DECISION_CONTRACT_VERSION
    assert provenance["decision_contract"]["schema_hash"] == direct_tool_schema_hash()
    assert provenance["runtime"]["transport"] == "openai_compatible_chat_completions"
    assert provenance["runtime"]["structured_output_mode"] == "function_calling"
    assert provenance["runtime"]["reasoning_effort"] == "none"
    validate_provenance(provenance)

    unset = build_provenance(
        args=_args(reasoning_effort=None),
        case_set_version="live_eval_v1",
        case_set_hash="c" * 64,
        prompt_hash="p" * 64,
        scoring_version="live_scoring_v2",
        runs_per_case=1,
        unique_cases=1,
        total_attempts=1,
        runner=lambda *args, **kwargs: _result(""),
    )
    assert unset["runtime"]["reasoning_effort"] is None


def test_cost_semantics_distinguish_local_and_hosted() -> None:
    common: dict[str, Any] = {
        "case_set_version": "live_eval_v1",
        "case_set_hash": "c" * 64,
        "prompt_hash": "p" * 64,
        "scoring_version": "live_scoring_v3",
        "runs_per_case": 1,
        "unique_cases": 1,
        "total_attempts": 1,
    }
    local = build_provenance(args=_args(), runner=lambda *args, **kwargs: _result(""), **common)
    hosted = build_provenance(
        args=_args(base_url="https://api.openai.com/v1"),
        runner=lambda *args, **kwargs: _result(""),
        **common,
    )
    assert local["usage"]["cost_status"] == "not_applicable"
    assert hosted["usage"]["cost_status"] == "unavailable"
    assert local["usage"]["cost"] is None
    assert hosted["usage"]["cost_currency"] is None


def test_git_metadata_is_safe_when_git_is_unavailable() -> None:
    def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("git missing")

    assert git_metadata(unavailable) == {"source_revision": None, "dirty_worktree": None}


def test_hardware_collection_is_optional_and_privacy_safe() -> None:
    metadata = _hardware_metadata(
        system=lambda: "UnknownOS",
        release=lambda: "1",
        machine=lambda: "arm64",
        processor=lambda: "test-cpu",
        environ={"SECRET_API_KEY": "must-not-be-serialized"},
    )
    assert metadata["architecture"] == "arm64"
    assert metadata["memory_bytes"] is None
    assert "SECRET_API_KEY" not in str(metadata)


def test_provenance_validator_rejects_contract_hash_mismatch() -> None:
    provenance = build_provenance(
        args=_args(base_url="https://api.openai.com/v1"),
        case_set_version="live_eval_v1",
        case_set_hash="c" * 64,
        prompt_hash="p" * 64,
        scoring_version="live_scoring_v3",
        runs_per_case=1,
        unique_cases=1,
        total_attempts=1,
        runner=lambda *args, **kwargs: _result(""),
    )
    provenance["decision_contract"]["schema_hash"] = "0" * 64
    with pytest.raises(ValueError, match="schema hash"):
        validate_provenance(provenance)


def test_historical_rescore_does_not_use_current_machine_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from evaluation.live_scoring_v3 import rescore_file

    source = "artifacts/live-eval/qwen3_5_9b_20260812T234047Z.json"
    raw = json.loads(open(source, encoding="utf-8").read())
    raw["metadata"].pop("provenance", None)
    frozen = tmp_path / "historical.json"
    frozen.write_text(json.dumps(raw), encoding="utf-8")

    monkeypatch.setattr(
        "evaluation.provenance._hardware_metadata",
        lambda **kwargs: {
            "machine": "CURRENT-MACHINE",
            "os": "CURRENT-OS",
            "architecture": "CURRENT-ARCH",
            "cpu": "CURRENT-CPU",
            "accelerator": "CURRENT-GPU",
            "memory_bytes": 123,
        },
    )
    result = rescore_file(frozen, tmp_path / "rescored.json")
    source_provenance = result.metadata["source_provenance"]
    assert source_provenance["runtime"]["runtime_version"] is None
    assert source_provenance["model"]["model_digest"] is None
    assert source_provenance["model"]["quantization"] is None
    assert source_provenance["hardware"]["accelerator"] is None
    assert result.metadata["derived_scoring"]["rescored_by_source_revision"]
