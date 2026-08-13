from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import AgentRequestType, Intent, SemanticDecisionV3
from evaluation.model_compatibility_matrix import (
    D2A_GATE_SCHEMA_VERSION,
    ELIGIBILITY_RULE_VERSION,
    EXPECTED_FUNCTION_SCHEMA_HASH,
    EXPECTED_SCHEMA_HASH,
    Eligibility,
    EvidenceOrigin,
    HistoricalEvidence,
    LocalModelIdentity,
    ModelCompatibilityCandidate,
    _fixed_contract_preflight,
    _local_settings,
    _run_files,
    build_matrix,
    candidate_manifest,
    discover_local_model,
    eligibility_for,
    import_historical_evidence,
    publish_matrix,
    publish_run,
    run_local_candidate,
    static_artifact_preflight,
    synthetic_run_artifact,
    targeted_subset_hash,
    targeted_subset_payload,
    unavailable_row,
    validate_subset_equivalence,
)
from evaluation.structured_output_v3_gate import (
    _arm_files,
    _gate_metadata,
    _settings,
    _synthetic_artifact,
)


class MockProvider:
    decision_contract_version = "semantic_decision_v3"

    def __init__(self, model: str = "qwen2.5:7b-instruct") -> None:
        template = OpenAICompatibleProvider(_local_settings(model))
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
        return OpenAICompatibleProvider(
            _local_settings("qwen2.5:7b-instruct")
        ).structured_schema_metadata()


def _identity(tag: str = "qwen2.5:7b-instruct") -> LocalModelIdentity:
    return LocalModelIdentity(
        tag=tag,
        digest="a" * 64,
        quantization="Q4_K_M",
        ollama_version="ollama version is 0.32.6",
        platform_architecture="arm64",
    )


def _failure_taxonomy(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "normalized_errors": {},
        "transport_failures": 0,
        "argument_decode_failures": 0,
    }
    payload.update(updates)
    return payload


def test_candidate_manifest_is_the_fixed_four_model_matrix() -> None:
    manifest = candidate_manifest()
    assert [(item.candidate_id, item.requested_model) for item in manifest] == [
        ("gpt_5_6_luna", "gpt-5.6-luna"),
        ("qwen3_5_4b", "qwen3.5:4b"),
        ("qwen2_5_7b_instruct", "qwen2.5:7b-instruct"),
        ("qwen3_5_9b", "qwen3.5:9b"),
    ]
    assert manifest[0].historical_evidence is not None
    assert manifest[1].historical_evidence is not None
    assert manifest[2].historical_evidence is None
    assert manifest[3].historical_evidence is None


def test_targeted_subset_is_identical_between_v1_1_and_v1_2() -> None:
    v1_1, v1_2 = validate_subset_equivalence()
    assert v1_1 == v1_2 == ("850f8adfa6ce890f4a6db1edadb87d9ac2549df4140d8bca5ee88beb12bb521e")
    assert (
        len(
            targeted_subset_payload(
                __import__("evaluation.live_cases", fromlist=["live_cases_v1_2"]).live_cases_v1_2()
            )
        )
        == 8
    )


def test_fixed_contract_and_transport_preflight() -> None:
    _fixed_contract_preflight()
    provider = OpenAICompatibleProvider(_local_settings("preflight"))
    assert provider.structured_schema_metadata()["contract_schema_hash"] == EXPECTED_SCHEMA_HASH
    assert (
        provider.structured_schema_metadata()["transport_schema_hash"]
        == EXPECTED_FUNCTION_SCHEMA_HASH
    )


@pytest.mark.parametrize(
    ("provider", "decoded", "typed", "timeouts", "taxonomy", "expected"),
    [
        (24, 24, 24, 0, _failure_taxonomy(), Eligibility.ELIGIBLE),
        (23, 23, 23, 1, _failure_taxonomy(), Eligibility.ELIGIBLE),
        (24, 24, 22, 0, _failure_taxonomy(), Eligibility.REVIEW),
        (24, 24, 21, 0, _failure_taxonomy(), Eligibility.REVIEW),
        (24, 24, 20, 0, _failure_taxonomy(), Eligibility.INELIGIBLE),
        (24, 24, 23, 2, _failure_taxonomy(), Eligibility.INELIGIBLE),
        (
            24,
            24,
            21,
            0,
            _failure_taxonomy(normalized_errors={"model_attributes_type@target": 3}),
            Eligibility.INELIGIBLE,
        ),
        (
            24,
            21,
            21,
            0,
            _failure_taxonomy(argument_decode_failures=3),
            Eligibility.INELIGIBLE,
        ),
    ],
)
def test_eligibility_rules_are_preregistered(
    provider: int,
    decoded: int,
    typed: int,
    timeouts: int,
    taxonomy: dict[str, Any],
    expected: Eligibility,
) -> None:
    assert (
        eligibility_for(
            provider_success=provider,
            arguments_decoded=decoded,
            typed_success=typed,
            timeout_count=timeouts,
            failure_taxonomy=taxonomy,
        )
        is expected
    )
    assert ELIGIBILITY_RULE_VERSION == "d2a_compatibility_gate_v1"


def test_experiment_invalid_is_not_a_model_quality_classification() -> None:
    assert (
        eligibility_for(
            provider_success=24,
            arguments_decoded=24,
            typed_success=24,
            timeout_count=0,
            failure_taxonomy=_failure_taxonomy(),
            experiment_valid=False,
        )
        is Eligibility.INVALID
    )


def _write_historical_fixture(tmp_path: Path) -> ModelCompatibilityCandidate:
    provider = OpenAICompatibleProvider(_settings(arm="qwen"))
    metadata = _gate_metadata(
        arm="qwen",
        diagnostic_id="historical-test",
        provider=provider,
        base_revision="f" * 40,
        model_metadata={
            "model_digest": ("2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"),
            "quantization": "Q4_K_M",
        },
    )
    artifact = _synthetic_artifact(metadata)
    artifact.provenance = {
        "runtime": {"runtime_version": "ollama version is 0.32.6"},
        "model": {},
    }
    directory = tmp_path / "historical-test"
    directory.mkdir()
    files = _arm_files(artifact)
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    hashes = {
        name: __import__("hashlib").sha256((directory / name).read_bytes()).hexdigest()
        for name in files
    }
    return ModelCompatibilityCandidate(
        candidate_id="qwen3_5_4b",
        display_name="Qwen3.5 4B",
        provider="ollama",
        requested_model="qwen3.5:4b",
        expected_model_family="qwen3.5:4b",
        role="test",
        historical_evidence=HistoricalEvidence(
            diagnostic_id="historical-test",
            attempts_sha256=hashes["attempts.json"],
            summary_sha256=hashes["summary.json"],
            markdown_sha256=hashes["summary.md"],
        ),
    )


def test_historical_import_hash_validates_json_and_recomputes_summary(tmp_path: Path) -> None:
    candidate = _write_historical_fixture(tmp_path)
    row = import_historical_evidence(candidate, tmp_path)
    assert row.evidence_origin is EvidenceOrigin.REUSED
    assert row.typed_semantic_decision_v3 == 24
    assert row.eligibility is Eligibility.ELIGIBLE
    assert row.runtime_version == "ollama version is 0.32.6"


def test_historical_hash_mismatch_stops_instead_of_rerunning(tmp_path: Path) -> None:
    candidate = _write_historical_fixture(tmp_path)
    (tmp_path / "historical-test" / "summary.md").write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="HISTORICAL_ARTIFACT_HASH_MISMATCH"):
        import_historical_evidence(candidate, tmp_path)


def test_local_discovery_records_identity_without_pull() -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "models": [
                    {
                        "name": "qwen3.5:9b",
                        "digest": "b" * 64,
                        "details": {"quantization_level": "Q4_K_M"},
                    }
                ]
            }

    commands: list[list[str]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ollama version is 0.32.6\n")

    identity = discover_local_model(
        "qwen3.5:9b",
        get=lambda *args, **kwargs: cast(httpx.Response, Response()),  # noqa: ARG005
        runner=runner,
    )
    assert identity is not None
    assert identity.digest == "b" * 64
    assert identity.quantization == "Q4_K_M"
    assert commands == [["ollama", "--version"]]
    source = Path("evaluation/model_compatibility_matrix.py").read_text(encoding="utf-8")
    assert "ollama pull" not in source


def test_absent_local_model_is_unavailable_not_incompatible() -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"models": []}

    identity = discover_local_model(
        "qwen3.5:9b",
        get=lambda *args, **kwargs: cast(httpx.Response, Response()),  # noqa: ARG005
    )
    assert identity is None
    row = unavailable_row(candidate_manifest()[3])
    assert row.eligibility is Eligibility.UNAVAILABLE
    assert row.evidence_origin is EvidenceOrigin.UNAVAILABLE


def test_static_and_atomic_artifact_pipeline(tmp_path: Path) -> None:
    static_artifact_preflight()
    candidate = candidate_manifest()[2]
    artifact = synthetic_run_artifact(candidate, _identity())
    destination = publish_run(artifact, tmp_path)
    assert set(path.name for path in destination.iterdir()) == {
        "attempts.json",
        "summary.json",
        "summary.md",
    }
    attempts = json.loads((destination / "attempts.json").read_text(encoding="utf-8"))
    assert attempts["status"] == "COMPLETE"
    assert attempts["metadata"]["diagnostic_schema_version"] == D2A_GATE_SCHEMA_VERSION
    serialized = "".join(_run_files(artifact).values())
    assert "Authorization" not in serialized
    assert "raw_arguments" not in serialized


def test_call_budget_is_one_warmup_plus_24_and_no_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "evaluation.model_compatibility_matrix._require_clean_tracked_worktree", lambda: None
    )
    provider = MockProvider()
    row, artifact = run_local_candidate(
        candidate=candidate_manifest()[2],
        identity=_identity(),
        diagnostic_id="mock-d2a-run",
        output_root=tmp_path,
        source_revision="f" * 40,
        provider_factory=lambda settings: cast(  # noqa: ARG005
            OpenAICompatibleProvider, provider
        ),
    )
    assert provider.calls == 25
    assert len(artifact.attempts) == 24
    assert row.typed_semantic_decision_v3 == 24
    assert row.eligibility is Eligibility.ELIGIBLE
    assert artifact.metadata.retry_count == 0


def test_artifact_failure_invalidates_without_rerun_or_complete_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "evaluation.model_compatibility_matrix._require_clean_tracked_worktree", lambda: None
    )
    provider = MockProvider()
    original = __import__(
        "evaluation.model_compatibility_matrix", fromlist=["_run_markdown"]
    )._run_markdown

    def fail_live(artifact: Any) -> str:
        if artifact.metadata.diagnostic_id == "failed-d2a-run":
            raise RuntimeError("render failed")
        return cast(str, original(artifact))

    monkeypatch.setattr("evaluation.model_compatibility_matrix._run_markdown", fail_live)
    with pytest.raises(RuntimeError, match="render failed"):
        run_local_candidate(
            candidate=candidate_manifest()[2],
            identity=_identity(),
            diagnostic_id="failed-d2a-run",
            output_root=tmp_path,
            source_revision="f" * 40,
            provider_factory=lambda settings: cast(  # noqa: ARG005
                OpenAICompatibleProvider, provider
            ),
        )
    assert provider.calls == 25
    assert not (tmp_path / "failed-d2a-run").exists()
    invalid = json.loads(
        (tmp_path / "invalidated" / "failed-d2a-run.json").read_text(encoding="utf-8")
    )
    assert invalid["status"] == "INVALID"
    assert invalid["generation_calls"] == 25


def test_matrix_has_exact_rows_and_separates_eligible_review_and_unavailable(
    tmp_path: Path,
) -> None:
    candidates = candidate_manifest()
    artifact = synthetic_run_artifact(candidates[2], _identity())
    destination = publish_run(artifact, tmp_path / "runs")
    base = unavailable_row(candidates[3])
    rows = [
        base.model_copy(
            update={
                "candidate_id": candidates[0].candidate_id,
                "candidate": candidates[0].display_name,
                "provider_runtime": "OpenAI API",
                "evidence_origin": EvidenceOrigin.REUSED,
                "eligibility": Eligibility.ELIGIBLE,
            }
        ),
        base.model_copy(
            update={
                "candidate_id": candidates[1].candidate_id,
                "candidate": candidates[1].display_name,
                "evidence_origin": EvidenceOrigin.REUSED,
                "eligibility": Eligibility.INELIGIBLE,
            }
        ),
        base.model_copy(
            update={
                "candidate_id": candidates[2].candidate_id,
                "candidate": candidates[2].display_name,
                "evidence_origin": EvidenceOrigin.NEW,
                "eligibility": Eligibility.REVIEW,
                "artifact_paths": {"attempts.json": str(destination / "attempts.json")},
            }
        ),
        base,
    ]
    matrix = build_matrix("matrix-test", "f" * 40, rows)
    assert matrix.d2b_eligible_candidates == ["GPT-5.6 Luna"]
    assert matrix.d2b_review_candidates == ["Qwen2.5 7B Instruct"]
    assert matrix.ineligible_candidates == ["Qwen3.5 4B"]
    assert matrix.unavailable_candidates == ["Qwen3.5 9B"]
    assert matrix.readiness == "D2A_REVIEW_REQUIRED"
    matrix_path = publish_matrix(matrix, candidates, tmp_path / "matrix")
    assert set(path.name for path in matrix_path.iterdir()) == {
        "manifest.json",
        "compatibility_matrix.json",
        "compatibility_matrix.md",
    }


def test_targeted_subset_hash_has_no_timestamp_or_runtime_input() -> None:
    source = Path("evaluation/model_compatibility_matrix.py").read_text(encoding="utf-8")
    assert targeted_subset_hash.__name__ in source
    payload = targeted_subset_payload(
        __import__("evaluation.live_cases", fromlist=["live_cases_v1_2"]).live_cases_v1_2()
    )
    assert all("timestamp" not in item for item in payload)


def test_privacy_contract_excludes_raw_payload_and_credentials() -> None:
    source = Path("evaluation/model_compatibility_matrix.py").read_text(encoding="utf-8")
    assert "raw_arguments" not in source
    assert "OPENAI_API_KEY" not in source
    assert "Authorization" not in source
    assert "hostname" not in source
