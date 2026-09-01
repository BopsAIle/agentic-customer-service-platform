from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import AgentRequestType, Intent, SemanticDecisionV3
from evaluation.structured_output_diagnostics import DIAGNOSTIC_CASE_IDS
from evaluation.structured_output_v3_gate import (
    CONTRACT_VERSION,
    HISTORICAL_INVALIDATED_RUNS,
    LUNA_MODEL,
    MAX_GENERATION_CALLS,
    MEASURED_ATTEMPTS,
    QWEN_DIGEST,
    QWEN_MODEL,
    REQUIRED_ARM_FILES,
    REQUIRED_COMPARISON_FILES,
    GateRunArtifact,
    StructuredOutputGateMetadata,
    _cases,
    _gate_metadata,
    _settings,
    _synthetic_artifact,
    _target_branch_requirements,
    artifact_set_complete,
    build_comparison_artifact,
    compatibility_classification,
    gate_configuration,
    publish_comparison_artifact,
    run_arm,
    static_artifact_preflight,
)


class MockProvider:
    decision_contract_version = CONTRACT_VERSION

    def __init__(self) -> None:
        template = OpenAICompatibleProvider(_settings(arm="qwen"))
        self._transport_schema = template._transport_schema
        self.calls = 0
        self.last_validation_diagnostic = None
        self.last_structured_call_metadata = {
            "structured_call_present": True,
            "tool_call_count": 1,
            "function_name_present": True,
            "arguments_present": True,
            "arguments_decoded": True,
            "argument_payload_kind": "object",
            "target_variant": None,
            "target_keys": [],
            "target_identifier_json_type": None,
        }

    def decide(self, **kwargs: Any) -> SemanticDecisionV3:
        del kwargs
        self.calls += 1
        return SemanticDecisionV3(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
            clarification_required=False,
        )

    def structured_schema_metadata(self) -> dict[str, Any]:
        template = OpenAICompatibleProvider(_settings(arm="qwen"))
        return template.structured_schema_metadata()


def _metadata(arm: str, diagnostic_id: str) -> StructuredOutputGateMetadata:
    provider = OpenAICompatibleProvider(_settings(arm=arm))  # type: ignore[arg-type]
    return _gate_metadata(
        arm=arm,  # type: ignore[arg-type]
        diagnostic_id=diagnostic_id,
        provider=provider,
        base_revision="f" * 40,
        model_metadata={
            "model_digest": QWEN_DIGEST if arm == "qwen" else None,
            "quantization": "Q4_K_M" if arm == "qwen" else None,
            "runtime_version": "0.32.6" if arm == "qwen" else None,
        },
    )


def test_v3_gate_configuration_is_methodologically_equal_across_arms() -> None:
    qwen = gate_configuration(arm="qwen", model_id=QWEN_MODEL)
    luna = gate_configuration(arm="luna", model_id=LUNA_MODEL)
    intentionally_different = {
        "provider",
        "model",
        "model_digest",
        "quantization",
        "runtime",
        "runtime_version",
    }
    assert {key: value for key, value in qwen.items() if key not in intentionally_different} == {
        key: value for key, value in luna.items() if key not in intentionally_different
    }
    assert qwen["decision_contract_version"] == CONTRACT_VERSION
    assert qwen["decision_schema_hash"] == (
        "9072994198f9d5586365548875c81760aa697be9604aaacc927892d2d9a39dd0"
    )
    assert qwen["prompt_hash"] == (
        "d2cf899be3b826285e8e8f8d2c3f7d1332d6b4f5ed2d0b90fbec5e4ab11cf365"
    )
    assert qwen["case_set_hash"] == (
        "ad00fd8120e8c5187f667ee95ae7c93c387ed371f168af9d2cd76bb34631bd08"
    )
    assert qwen["reasoning_effort"] == "none"
    assert qwen["temperature"] == 0.0
    assert qwen["timeout_seconds"] == 30.0
    assert qwen["retry_count"] == 0
    assert qwen["measured_attempts"] == MEASURED_ATTEMPTS == 24
    assert qwen["warmup_count"] == 1
    assert MAX_GENERATION_CALLS == 25


def test_v3_gate_uses_exact_v1_1_targeted_cases() -> None:
    cases = _cases()
    assert tuple(case_id for case_id in DIAGNOSTIC_CASE_IDS if case_id in cases) == (
        DIAGNOSTIC_CASE_IDS
    )
    assert cases["en-fake-id"].rendered_input() == "Cancel order 999999."


def test_v3_transport_requires_explicit_identifiers() -> None:
    provider = OpenAICompatibleProvider(_settings(arm="qwen"))
    assert _target_branch_requirements(provider) == {
        "explicit_order": ["type", "order_id"],
        "latest_order": ["type"],
        "explicit_ticket": ["type", "ticket_id"],
    }


def test_metadata_regression_renders_decision_contract_version_without_alias() -> None:
    artifact = _synthetic_artifact(_metadata("qwen", "old-key-regression"))
    files = __import__("evaluation.structured_output_v3_gate", fromlist=["_arm_files"])._arm_files(
        artifact
    )
    assert "semantic_decision_v3" in files["summary.md"]
    assert "contract_version" not in type(artifact.metadata).model_fields
    assert artifact.metadata.decision_contract_version == "semantic_decision_v3"


def test_full_mocked_gate_pipeline_writes_and_reads_complete_artifacts(
    tmp_path: Path,
) -> None:
    provider = MockProvider()
    artifact = run_arm(
        arm="qwen",
        diagnostic_id="mock-qwen-gate",
        output_root=tmp_path,
        model_metadata={
            "model_digest": QWEN_DIGEST,
            "quantization": "Q4_K_M",
            "runtime_version": "0.32.6",
        },
        require_clean_source=False,
        provider_factory=lambda settings: cast(  # noqa: ARG005
            OpenAICompatibleProvider, provider
        ),
    )
    destination = tmp_path / "mock-qwen-gate"
    assert provider.calls == MAX_GENERATION_CALLS
    assert artifact_set_complete(destination, REQUIRED_ARM_FILES)
    attempts = json.loads((destination / "attempts.json").read_text(encoding="utf-8"))
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    markdown = (destination / "summary.md").read_text(encoding="utf-8")
    assert attempts["status"] == "COMPLETE"
    assert len(attempts["attempts"]) == 24
    assert summary["metadata"]["decision_contract_version"] == CONTRACT_VERSION
    assert summary["metadata"]["dataset_version"] == "live_eval_v1_1"
    assert artifact.summary["typed_decision_success"] == 24
    assert CONTRACT_VERSION in markdown
    serialized = json.dumps(attempts) + json.dumps(summary) + markdown
    assert "sentinel-secret" not in serialized
    assert "Authorization" not in serialized


def test_static_preflight_and_dual_comparison_pipeline(tmp_path: Path) -> None:
    qwen = _synthetic_artifact(_metadata("qwen", "synthetic-qwen"))
    luna = _synthetic_artifact(_metadata("luna", "synthetic-luna"))
    static_artifact_preflight(qwen.metadata, luna.metadata)
    comparison = build_comparison_artifact(
        comparison_id="synthetic-comparison", qwen=qwen, luna=luna
    )
    destination = publish_comparison_artifact(comparison, tmp_path)
    assert artifact_set_complete(destination, REQUIRED_COMPARISON_FILES)
    payload = json.loads((destination / "comparison.json").read_text(encoding="utf-8"))
    markdown = (destination / "comparison.md").read_text(encoding="utf-8")
    assert payload["metadata"]["decision_contract_version"] == CONTRACT_VERSION
    assert payload["metadata"]["qwen_diagnostic_id"] == "synthetic-qwen"
    assert payload["metadata"]["luna_diagnostic_id"] == "synthetic-luna"
    assert "synthetic-qwen" in markdown
    assert "synthetic-luna" in markdown


def test_render_failure_invalidates_without_complete_artifact_or_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = MockProvider()

    def fail_render(artifact: GateRunArtifact) -> str:
        del artifact
        raise KeyError("contract_version")

    monkeypatch.setattr("evaluation.structured_output_v3_gate._render_arm_markdown", fail_render)
    with pytest.raises(KeyError, match="contract_version"):
        run_arm(
            arm="qwen",
            diagnostic_id="failed-render",
            output_root=tmp_path,
            model_metadata={
                "model_digest": QWEN_DIGEST,
                "quantization": "Q4_K_M",
            },
            require_clean_source=False,
            provider_factory=lambda settings: cast(  # noqa: ARG005
                OpenAICompatibleProvider, provider
            ),
            render_preflight=False,
        )
    assert provider.calls == MAX_GENERATION_CALLS
    assert not (tmp_path / "failed-render").exists()
    invalid = json.loads(
        (tmp_path / "invalidated" / "failed-render.json").read_text(encoding="utf-8")
    )
    assert invalid == {
        "status": "INVALID",
        "diagnostic_id": "failed-render",
        "included_in_results": False,
        "generation_calls": 25,
        "reason": "artifact_write_failure",
    }


def test_missing_required_metadata_fails_before_generation() -> None:
    payload = _metadata("qwen", "metadata-failure").model_dump()
    payload.pop("decision_contract_version")
    with pytest.raises(ValueError):
        StructuredOutputGateMetadata.model_validate(payload)


def test_historical_invalid_run_is_explicitly_noncanonical() -> None:
    assert [item.model_dump(mode="json") for item in HISTORICAL_INVALIDATED_RUNS] == [
        {
            "status": "INVALID",
            "diagnostic_id": "structured_output_v3_qwen3_5_4b_20260813T191200Z",
            "included_in_results": False,
            "generation_calls": 25,
            "reason": "artifact_write_failure",
        }
    ]


def test_compatibility_classification_is_explicit() -> None:
    assert compatibility_classification(24, 24) == "HIGH_COMPATIBILITY"
    assert compatibility_classification(23, 24) == "HIGH_COMPATIBILITY"
    assert compatibility_classification(20, 24) == "PARTIAL_COMPATIBILITY"
    assert compatibility_classification(0, 24) == "LOW_COMPATIBILITY"
    assert compatibility_classification(0, 0) == "EXPERIMENT_INVALID"


def test_luna_gate_never_accepts_an_unverified_or_fallback_model(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="OPENAI_LUNA_NOT_AVAILABLE"):
        run_arm(
            arm="luna",
            diagnostic_id="must-not-run",
            output_root=tmp_path,
            api_key="sentinel-secret",
            discovered_model_id="gpt-5.6-terra",
            require_clean_source=False,
        )
    assert not list(tmp_path.iterdir())


def test_gate_source_contains_no_secret_or_raw_value_persistence() -> None:
    source = Path("evaluation/structured_output_v3_gate.py").read_text(encoding="utf-8")
    assert "Authorization" not in source
    assert "raw_arguments" not in source
    assert "sentinel-secret" not in source
    serialized = json.dumps(gate_configuration(arm="luna", model_id=LUNA_MODEL))
    assert "api_key" not in serialized
