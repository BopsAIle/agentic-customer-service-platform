from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.schemas import AgentRequestType, Intent, SemanticDecisionV3
from app.core.config import Settings
from evaluation.d2b_approval import build_review_approval, write_review_approval
from evaluation.d2b_runner import (
    MAX_GENERATION_CALLS,
    MEASURED_ATTEMPTS,
    MODEL,
    REQUIRED_FILES,
    D2bProvider,
    _atomic_publish,
    _cases,
    _settings,
    artifact_hashes,
    artifact_set_complete,
    deterministic_runtime_checks,
    deterministic_schedule,
    run_experiment,
    schedule_hash,
    static_artifact_preflight,
    validate_approved_run,
)
from evaluation.d2b_spec import CONTRACT_SCHEMA_HASH, FUNCTION_SCHEMA_HASH

EXPERIMENT_ID = "d2b_semantic_v3_20260814T010000Z"
SOURCE_REVISION = "a" * 40


class MockSemanticProvider:
    decision_contract_version = "semantic_decision_v3"

    def __init__(self) -> None:
        self.calls = 0
        self._last_validation_diagnostic = None
        self._last_structured_call_metadata: dict[str, Any] = {
            "structured_call_present": True,
            "tool_call_count": 1,
            "function_name_present": True,
            "arguments_present": True,
            "arguments_decoded": True,
            "argument_payload_kind": "mapping",
            "target_variant": None,
            "target_keys": [],
            "target_identifier_json_type": None,
        }

    @property
    def last_validation_diagnostic(self) -> None:
        return self._last_validation_diagnostic

    @property
    def last_structured_call_metadata(self) -> dict[str, Any]:
        return dict(self._last_structured_call_metadata)

    def structured_schema_metadata(self) -> dict[str, Any]:
        return {
            "contract_schema_hash": CONTRACT_SCHEMA_HASH,
            "transport_schema_hash": FUNCTION_SCHEMA_HASH,
            "transport_schema_available": True,
        }

    def decide(self, **kwargs: Any) -> SemanticDecisionV3:
        del kwargs
        self.calls += 1
        return SemanticDecisionV3(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
        )


def _approval(tmp_path: Path) -> tuple[Path, str]:
    approval = build_review_approval(
        approval_record_id="d2b-test-review",
        reviewer_identity="reviewer@example.test",
        approved_at=datetime(2026, 8, 14, 1, tzinfo=UTC),
        experiment_id=EXPERIMENT_ID,
        source_revision=SOURCE_REVISION,
    )
    path = tmp_path / "d2b-test-review.json"
    return path, write_review_approval(approval, path)


def _safe_runtime_checks() -> dict[str, Any]:
    return {
        "unsafe_execution_count": 0,
        "confirmation_bypass_count": 0,
        "unauthorized_mutation_count": 0,
        "duplicate_mutation_count": 0,
        "confirmation_required": True,
        "mutation_after_confirmation": True,
        "stable_action_id": True,
        "replay_safe": True,
        "policy_correct": True,
    }


def test_d2b_configuration_is_frozen_semantic_v3_luna() -> None:
    settings = _settings("sentinel-not-persisted")
    assert settings.agent_decision_contract_version == "semantic_decision_v3"
    assert settings.llm_model == "gpt-5.6-luna"
    assert settings.llm_base_url == "https://api.openai.com/v1"
    assert settings.llm_structured_output_mode == "function_calling"
    assert settings.llm_reasoning_effort == "none"
    assert settings.llm_temperature == 0.0
    assert settings.llm_timeout_seconds == 30.0
    source = Path("evaluation/d2b_runner.py").read_text(encoding="utf-8")
    assert "architecture_ab_d1b" not in source
    assert "from evaluation.live import" not in source


def test_d2b_approval_binds_source_dataset_contract_and_candidate(tmp_path: Path) -> None:
    path, digest = _approval(tmp_path)
    approved = validate_approved_run(
        approval_path=path,
        approval_sha256=digest,
        source_revision=SOURCE_REVISION,
        require_clean_source=False,
    )
    assert approved.metadata.experiment_id == EXPERIMENT_ID
    assert approved.metadata.source_revision == SOURCE_REVISION
    assert approved.metadata.dataset_version == "live_eval_v1_2"
    assert approved.metadata.contract_version == "semantic_decision_v3"
    assert approved.metadata.model == MODEL
    assert approved.metadata.provider == "official OpenAI API"
    assert approved.metadata.measured_attempts == MEASURED_ATTEMPTS
    static_artifact_preflight(approved)

    with pytest.raises(RuntimeError, match="D2B_REVIEW_APPROVAL_MISMATCH"):
        validate_approved_run(
            approval_path=path,
            approval_sha256=digest,
            source_revision="b" * 40,
            require_clean_source=False,
        )


def test_d2b_schedule_is_deterministic_and_complete() -> None:
    first = deterministic_schedule(_cases())
    second = deterministic_schedule(_cases())
    assert first == second
    assert len(first) == MEASURED_ATTEMPTS
    assert schedule_hash(first) == schedule_hash(second)
    assert (
        schedule_hash(first) == "5f3da649e6937f8c602954718e52bb07c0de3a7cc003162f8cef781aff727b57"
    )
    assert [(item.case_id, item.run_index) for item in first[:3]] == [
        ("en-order-latest", 1),
        ("en-order-latest", 2),
        ("en-order-latest", 3),
    ]


def test_d2b_atomic_publish_never_replaces_existing_directory(tmp_path: Path) -> None:
    destination = tmp_path / "result"
    _atomic_publish(destination, {"manifest.json": '{"status":"COMPLETE"}\n'})
    original = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        _atomic_publish(destination, {"manifest.json": '{"status":"CHANGED"}\n'})
    assert (destination / "manifest.json").read_bytes() == original
    assert not list(tmp_path.glob(".result.*"))


def test_mocked_d2b_pipeline_enforces_budget_complete_artifacts_and_privacy(
    tmp_path: Path,
) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider = MockSemanticProvider()

    def factory(settings: Settings) -> D2bProvider:
        assert settings.llm_api_key == "sentinel-api-key"
        return provider

    destination = run_experiment(
        approval_path=approval_path,
        approval_sha256=approval_digest,
        output_root=tmp_path / "artifacts",
        api_key="sentinel-api-key",
        discovered_model_id=MODEL,
        provider_factory=factory,
        runtime_checks=_safe_runtime_checks,
        source_revision=SOURCE_REVISION,
        require_clean_source=False,
    )
    assert provider.calls == MAX_GENERATION_CALLS
    assert artifact_set_complete(destination)
    hashes = artifact_hashes(destination)
    assert set(hashes) == REQUIRED_FILES
    assert hashes == artifact_hashes(destination)

    attempts = json.loads((destination / MODEL / "attempts.json").read_text(encoding="utf-8"))
    assert attempts["status"] == "COMPLETE"
    assert len(attempts["attempts"]) == MEASURED_ATTEMPTS
    summary = json.loads((destination / MODEL / "summary.json").read_text(encoding="utf-8"))
    assert summary["call_accounting"] == {
        "warmup": 1,
        "measured": 84,
        "total": 85,
        "retry_count": 0,
    }
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in destination.rglob("*") if path.is_file()
    )
    for prohibited in (
        "sentinel-api-key",
        "Where is my latest order?",
        "Cancel order 999999.",
        '"customer_id"',
        '"order_id": 3',
        '"reason":',
        "Authorization",
    ):
        assert prohibited not in rendered


def test_generation_harness_failure_publishes_invalid_without_rerun(tmp_path: Path) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider = MockSemanticProvider()

    def fail_runtime_checks() -> dict[str, Any]:
        raise RuntimeError("synthetic-runtime-check-failure")

    output_root = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="synthetic-runtime-check-failure"):
        run_experiment(
            approval_path=approval_path,
            approval_sha256=approval_digest,
            output_root=output_root,
            api_key="sentinel-api-key",
            discovered_model_id=MODEL,
            provider_factory=lambda settings: provider,
            runtime_checks=fail_runtime_checks,
            source_revision=SOURCE_REVISION,
            require_clean_source=False,
        )
    assert provider.calls == MAX_GENERATION_CALLS
    assert not (output_root / EXPERIMENT_ID).exists()
    invalid = output_root / f"{EXPERIMENT_ID}.invalid" / "invalid.json"
    payload = json.loads(invalid.read_text(encoding="utf-8"))
    assert payload == {
        "status": "INVALID",
        "artifact_type": "d2b_invalid_run",
        "experiment_id": EXPERIMENT_ID,
        "source_revision": SOURCE_REVISION,
        "approval_record_id": "d2b-test-review",
        "generation_calls": 85,
        "stage": "deterministic_runtime_checks",
        "error_type": "RuntimeError",
        "included_in_results": False,
        "automatic_rerun": False,
    }


def test_invalid_approval_stops_before_provider_or_artifacts(tmp_path: Path) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider_created = False

    def factory(settings: Settings) -> D2bProvider:
        nonlocal provider_created
        del settings
        provider_created = True
        return MockSemanticProvider()

    output_root = tmp_path / "artifacts"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_experiment(
            approval_path=approval_path,
            approval_sha256="0" * 64,
            output_root=output_root,
            api_key="sentinel-api-key",
            discovered_model_id=MODEL,
            provider_factory=factory,
            runtime_checks=_safe_runtime_checks,
            source_revision=SOURCE_REVISION,
            require_clean_source=False,
        )
    assert provider_created is False
    assert not output_root.exists()


def test_d2b_deterministic_runtime_safety_checks_are_clean() -> None:
    result = deterministic_runtime_checks()
    assert result["unsafe_execution_count"] == 0
    assert result["confirmation_bypass_count"] == 0
    assert result["unauthorized_mutation_count"] == 0
    assert result["duplicate_mutation_count"] == 0
    assert result["stable_action_id"] is True
    assert result["replay_safe"] is True
    assert result["policy_correct"] is True
    assert result["symbolic_destructive_target"]["safe"] is True
    assert result["ungrounded_explicit_target"]["safe"] is True
    assert result["fake_user_supplied_id"]["safe"] is True
