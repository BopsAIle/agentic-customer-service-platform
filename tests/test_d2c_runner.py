from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.schemas import AgentRequestType, Intent, SemanticDecisionV3
from app.core.config import Settings
from evaluation.d2c_approval import build_review_approval, write_review_approval
from evaluation.d2c_oracle import CONTRACT_SCHEMA_HASH, FUNCTION_SCHEMA_HASH, D2cObservedOutcome
from evaluation.d2c_runner import (
    MEASURED_EXECUTIONS,
    MODEL,
    REQUIRED_FILES,
    D2cAttemptArtifact,
    D2cProvider,
    _atomic_publish,
    _attempt_from_observation,
    _settings,
    artifact_hashes,
    artifact_set_complete,
    run_experiment,
    static_artifact_preflight,
    validate_approved_run,
)
from evaluation.live_eval_v2 import live_eval_v2_cases

EXPERIMENT_ID = "d2c_semantic_v3_20260814T020000Z"
SOURCE_REVISION = "a" * 40


class MockProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def last_validation_diagnostic(self) -> None:
        return None

    @property
    def last_structured_call_metadata(self) -> dict[str, Any]:
        return {
            "structured_call_present": True,
            "function_name_present": True,
            "arguments_present": True,
            "arguments_decoded": True,
        }

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


class FailedWarmupProvider(MockProvider):
    def decide(self, **kwargs: Any) -> SemanticDecisionV3:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic warmup failure")
        return SemanticDecisionV3(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
        )


def _approval(tmp_path: Path) -> tuple[Path, str]:
    approval = build_review_approval(
        approval_record_id="d2c-test-review",
        reviewer_identity="reviewer@example.test",
        approved_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
        experiment_id=EXPERIMENT_ID,
        source_revision=SOURCE_REVISION,
    )
    path = tmp_path / "d2c-test-review.json"
    return path, write_review_approval(approval, path)


def _synthetic_attempt(entry: Any, case: Any) -> D2cAttemptArtifact:
    observed = D2cObservedOutcome(
        case_id=case.case_id,
        provider_success=True,
        structured_output_success=True,
        schema_valid=True,
        actual_intent=case.semantic.accepted_intents[0],
        actual_request_type=case.semantic.accepted_request_types[0],
        actual_target_variant=case.semantic.accepted_target_variants[0],
        target_identifier_match=(
            True if case.semantic.expected_order_id or case.semantic.expected_ticket_id else None
        ),
        concrete_identifier_origin={
            "user_provided": "user_provided",
            "symbolic": "server_resolved",
            "none": "none",
        }[case.semantic.identifier_origin],
        actual_clarification=case.semantic.clarification_required,
        actual_execution_path=case.deterministic.accepted_execution_paths[0],
        actual_grounding=case.deterministic.grounding,
        actual_target_admissibility=case.deterministic.target_admissibility,
        actual_compiler=case.deterministic.compiler,
        actual_resolver=case.deterministic.resolver,
        actual_policy=case.deterministic.policy,
        provider_latency_ms=1.0,
        end_to_end_latency_ms=1.1,
    )
    return _attempt_from_observation(entry, case, observed, {}, None)


def test_d2c_configuration_is_frozen_semantic_v3_luna() -> None:
    settings = _settings("sentinel-not-persisted")
    assert settings.agent_decision_contract_version == "semantic_decision_v3"
    assert settings.llm_model == "gpt-5.6-luna"
    assert settings.llm_base_url == "https://api.openai.com/v1"
    assert settings.llm_structured_output_mode == "function_calling"
    assert settings.llm_reasoning_effort == "none"
    assert settings.llm_temperature == 0.0
    assert settings.llm_timeout_seconds == 30.0
    source = Path("evaluation/d2c_runner.py").read_text(encoding="utf-8")
    assert "architecture_ab_d1b" not in source
    assert "from evaluation.live import" not in source


def test_d2c_approval_binds_all_frozen_inputs_and_budget(tmp_path: Path) -> None:
    path, digest = _approval(tmp_path)
    approved = validate_approved_run(
        approval_path=path,
        approval_sha256=digest,
        source_revision=SOURCE_REVISION,
        require_clean_source=False,
    )
    assert approved.metadata.experiment_id == EXPERIMENT_ID
    assert approved.metadata.source_revision == SOURCE_REVISION
    assert approved.metadata.dataset_version == "live_eval_v2"
    assert approved.metadata.contract_version == "semantic_decision_v3"
    assert approved.metadata.model == MODEL
    assert approved.metadata.measured_executions == MEASURED_EXECUTIONS
    assert len(approved.schedule) == MEASURED_EXECUTIONS
    assert [entry.ordinal for entry in approved.schedule] == list(range(1, 541))
    static_artifact_preflight(approved)

    with pytest.raises(RuntimeError, match="D2C_REVIEW_APPROVAL_MISMATCH"):
        validate_approved_run(
            approval_path=path,
            approval_sha256=digest,
            source_revision="b" * 40,
            require_clean_source=False,
        )


def test_d2c_atomic_publish_and_hash_verification(tmp_path: Path) -> None:
    destination = tmp_path / "result"
    _atomic_publish(destination, {"manifest.json": '{"status":"COMPLETE"}\n'})
    original = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        _atomic_publish(destination, {"manifest.json": '{"status":"CHANGED"}\n'})
    assert (destination / "manifest.json").read_bytes() == original
    assert not list(tmp_path.glob(".result.*"))


def test_d2c_pipeline_is_complete_private_and_exactly_540(tmp_path: Path) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider = MockProvider()
    destination = run_experiment(
        approval_path=approval_path,
        approval_sha256=approval_digest,
        output_root=tmp_path / "artifacts",
        api_key="sentinel-api-key",
        discovered_model_id=MODEL,
        provider_factory=lambda settings: provider,
        source_revision=SOURCE_REVISION,
        require_clean_source=False,
    )
    # 18 measured provider-fault fixtures are deterministic and make no provider request.
    assert provider.calls == 523
    assert artifact_set_complete(destination)
    assert set(artifact_hashes(destination)) == REQUIRED_FILES
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert summary["call_accounting"] == {
        "warmup_calls": 1,
        "measured_executions": 540,
        "provider_calls": 523,
        "retry_count": 0,
    }
    attempts = json.loads((destination / "attempts.json").read_text(encoding="utf-8"))
    assert len(attempts["attempts"]) == 540
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in destination.rglob("*") if path.is_file()
    )
    for prohibited in (
        "sentinel-api-key",
        "Where is my latest order?",
        "Cancel order 3.",
        '"order_id"',
        '"ticket_id"',
        '"reason"',
        "Authorization",
        "system prompt",
    ):
        assert prohibited not in rendered


def test_invalid_approval_stops_before_provider_and_artifacts(tmp_path: Path) -> None:
    path, _ = _approval(tmp_path)
    provider_created = False

    def factory(settings: Settings) -> D2cProvider:
        nonlocal provider_created
        del settings
        provider_created = True
        return MockProvider()

    output_root = tmp_path / "artifacts"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_experiment(
            approval_path=path,
            approval_sha256="0" * 64,
            output_root=output_root,
            api_key="sentinel-api-key",
            discovered_model_id=MODEL,
            provider_factory=factory,
            source_revision=SOURCE_REVISION,
            require_clean_source=False,
        )
    assert provider_created is False
    assert not output_root.exists()


def test_failed_warmup_is_unscored_and_measured_execution_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider = FailedWarmupProvider()

    def synthetic_run_attempt(*, entry: Any, case: Any, provider: Any, budget: Any) -> Any:
        del provider
        budget.consume_measured(provider_call=True)
        return _synthetic_attempt(entry, case)

    monkeypatch.setattr("evaluation.d2c_runner._run_attempt", synthetic_run_attempt)
    destination = run_experiment(
        approval_path=approval_path,
        approval_sha256=approval_digest,
        output_root=tmp_path / "artifacts",
        api_key="sentinel-api-key",
        discovered_model_id=MODEL,
        provider_factory=lambda settings: provider,
        source_revision=SOURCE_REVISION,
        require_clean_source=False,
    )
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert summary["warmup"] == {
        "status": "FAILED",
        "scored": False,
        "failure_category": "PROVIDER_FAILURE",
        "validation_stage": None,
    }
    assert summary["call_accounting"]["measured_executions"] == 540
    assert summary["metrics"]["routing_over_total"]["eligible"] == 540


def test_artifact_failure_is_invalid_and_never_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval_path, approval_digest = _approval(tmp_path)
    provider = MockProvider()
    cases = {case.case_id: case for case in live_eval_v2_cases()}

    def synthetic_run_attempt(*, entry: Any, case: Any, provider: Any, budget: Any) -> Any:
        del provider
        budget.consume_measured(provider_call=True)
        return _synthetic_attempt(entry, cases[case.case_id])

    monkeypatch.setattr("evaluation.d2c_runner._run_attempt", synthetic_run_attempt)
    monkeypatch.setattr("evaluation.d2c_runner.static_artifact_preflight", lambda approved: None)
    monkeypatch.setattr(
        "evaluation.d2c_runner._artifact_payloads",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render-failure")),
    )
    output_root = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="render-failure"):
        run_experiment(
            approval_path=approval_path,
            approval_sha256=approval_digest,
            output_root=output_root,
            api_key="sentinel-api-key",
            discovered_model_id=MODEL,
            provider_factory=lambda settings: provider,
            source_revision=SOURCE_REVISION,
            require_clean_source=False,
        )
    assert provider.calls == 1
    assert not (output_root / EXPERIMENT_ID).exists()
    invalid = json.loads(
        (output_root / f"{EXPERIMENT_ID}.invalid" / "invalid.json").read_text(encoding="utf-8")
    )
    assert invalid["status"] == "INVALID"
    assert invalid["measured_executions"] == 540
    assert invalid["provider_calls"] == 541
    assert invalid["stage"] == "artifact_generation"
    assert invalid["automatic_rerun"] is False
