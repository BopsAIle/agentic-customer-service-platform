from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from app.agent.decision_compiler import DecisionCompiler
from app.agent.schemas import (
    AgentRequestType,
    ExplicitOrderTargetV3,
    Intent,
    LatestOrderTargetV3,
    SemanticDecisionV3,
    StructuredDecision,
)
from evaluation.architecture_ab_d1b import (
    DIRECT_CONTRACT,
    MAX_GENERATION_CALLS,
    MODEL,
    REQUIRED_FILES,
    SEMANTIC_CONTRACT,
    TimedResolver,
    _cases,
    _layer_b,
    _metadata,
    _schedule,
    _semantic_outcome_v3,
    _settings,
    artifact_hashes,
    artifact_set_complete,
    run_experiment,
    static_artifact_preflight,
)
from evaluation.fixtures import evaluation_session


class MockContractProvider:
    def __init__(self, contract: str) -> None:
        self.decision_contract_version = contract
        self.calls = 0
        template = __import__(
            "app.agent.llm.provider", fromlist=["OpenAICompatibleProvider"]
        ).OpenAICompatibleProvider(_settings(cast(Any, contract), "not-persisted"))
        self._metadata = template.structured_schema_metadata()

    def decide(self, **kwargs: Any) -> StructuredDecision | SemanticDecisionV3:
        del kwargs
        self.calls += 1
        if self.decision_contract_version == DIRECT_CONTRACT:
            return StructuredDecision(
                intent=Intent.UNKNOWN,
                request_type=AgentRequestType.UNCLEAR,
            )
        return SemanticDecisionV3(
            intent=Intent.UNKNOWN,
            request_type=AgentRequestType.UNCLEAR,
        )

    def structured_schema_metadata(self) -> dict[str, Any]:
        return dict(self._metadata)


def test_d1b_frozen_configuration_and_counterbalanced_schedule() -> None:
    cases = _cases()
    schedule = _schedule(cases)
    assert len(cases) == 28
    assert sum(case.language == "en" for case in cases) == 14
    assert sum(case.language == "tr" for case in cases) == 14
    assert len(schedule) == 84
    assert {item["first"] for item in schedule} == {DIRECT_CONTRACT, SEMANTIC_CONTRACT}
    assert MAX_GENERATION_CALLS == 170
    assert MODEL == "gpt-5.6-luna"
    direct = _settings(DIRECT_CONTRACT, "not-persisted")
    semantic = _settings(SEMANTIC_CONTRACT, "not-persisted")
    intentionally_different = {"agent_decision_contract_version"}
    direct_values = direct.model_dump()
    semantic_values = semantic.model_dump()
    assert {
        key: value for key, value in direct_values.items() if key not in intentionally_different
    } == {
        key: value for key, value in semantic_values.items() if key not in intentionally_different
    }
    assert direct.llm_temperature == semantic.llm_temperature == 0.0
    assert direct.llm_reasoning_effort == semantic.llm_reasoning_effort == "none"
    assert direct.llm_timeout_seconds == semantic.llm_timeout_seconds == 30.0


def test_d1b_metadata_and_static_artifact_preflight() -> None:
    provider = cast(
        Any,
        __import__(
            "app.agent.llm.provider", fromlist=["OpenAICompatibleProvider"]
        ).OpenAICompatibleProvider(_settings(SEMANTIC_CONTRACT, "not-persisted")),
    )
    metadata = _metadata(
        experiment_id="d1b-static-preflight",
        semantic_provider=provider,
        source_revision="f" * 40,
        schedule=_schedule(_cases()),
    )
    assert metadata.direct_schema_hash == (
        "c172844788a5bdac58f92f0a4ee359bac108f5de087ff6ccfe20182f72070c20"
    )
    assert metadata.direct_prompt_hash == (
        "f51a66c3f3b914867061f59d1970ab0c0c0b7dc52db880fac97a7397c1d2d90b"
    )
    assert metadata.semantic_schema_hash == (
        "9072994198f9d5586365548875c81760aa697be9604aaacc927892d2d9a39dd0"
    )
    assert metadata.semantic_function_schema_hash == (
        "0580240826edb240d9dbd371f85bbb9e3c7f0d582a3b57c919a3ab363feaf8ef"
    )
    assert metadata.semantic_prompt_hash == (
        "d2cf899be3b826285e8e8f8d2c3f7d1332d6b4f5ed2d0b90fbec5e4ab11cf365"
    )
    assert metadata.case_set_hash == (
        "ad00fd8120e8c5187f667ee95ae7c93c387ed371f168af9d2cd76bb34631bd08"
    )
    static_artifact_preflight(metadata)


def test_semantic_v3_layer_a_applies_grounding_and_target_admissibility() -> None:
    cases = {case.id: case for case in _cases()}
    with evaluation_session() as session:
        resolver = TimedResolver(session)
        compiler = DecisionCompiler(resolver)
        ungrounded = _semantic_outcome_v3(
            cases["en-cancel-no-id"],
            1,
            SemanticDecisionV3(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=ExplicitOrderTargetV3(type="explicit_order", order_id=3),
            ),
            True,
            1.0,
            1.0,
            timeout=False,
            error_type=None,
            execution_order=SEMANTIC_CONTRACT,
            compiler=compiler,
            resolver=resolver,
        )
        symbolic = _semantic_outcome_v3(
            cases["en-cancel-no-id"],
            2,
            SemanticDecisionV3(
                intent=Intent.ORDER_CANCEL,
                request_type=AgentRequestType.WRITE_ACTION,
                target=LatestOrderTargetV3(type="latest_order"),
            ),
            True,
            1.0,
            1.0,
            timeout=False,
            error_type=None,
            execution_order=SEMANTIC_CONTRACT,
            compiler=compiler,
            resolver=resolver,
        )
    assert ungrounded.grounding_status == "ungrounded"
    assert ungrounded.grounding_intervention is True
    assert ungrounded.actual_tool is None
    assert ungrounded.hallucinated_identifier is True
    assert symbolic.target_admissibility_status == "requires_clarification"
    assert symbolic.target_admissibility_intervention is True
    assert symbolic.actual_tool is None
    assert symbolic.pre_policy_unsafe_action is False
    assert resolver.calls == 0


def test_layer_b_exercises_both_confirmations_and_semantic_boundaries() -> None:
    layer = _layer_b()
    for contract in (DIRECT_CONTRACT, SEMANTIC_CONTRACT):
        assert layer[contract]["cancellation_exercised"] is True
        assert layer[contract]["confirmation_required"] is True
        assert layer[contract]["mutation_before_confirmation"] is False
        assert layer[contract]["mutation_after_confirmation"] is True
        assert layer[contract]["action_id_stable"] is True
        assert layer[contract]["receipt_count"] == 1
        assert layer[contract]["replay_safe"] is True
        assert layer[contract]["unsafe_execution_count"] == 0
        assert layer[contract]["confirmation_bypass_count"] == 0
        assert layer[contract]["duplicate_mutation_count"] == 0
    semantic = layer[SEMANTIC_CONTRACT]
    assert semantic["symbolic_destructive_target"]["safe"] is True
    assert semantic["ungrounded_explicit_target"]["safe"] is True
    assert semantic["fake_user_supplied_id"] == {
        "grounded": True,
        "hallucinated": False,
        "business_validation_rejected": True,
        "mutation": False,
        "receipt_count": 0,
        "safe": True,
    }


def test_mocked_canonical_pipeline_enforces_budget_and_atomic_artifacts(
    tmp_path: Path,
) -> None:
    providers: dict[str, MockContractProvider] = {}

    def factory(settings: Any) -> Any:
        provider = MockContractProvider(settings.agent_decision_contract_version)
        providers[settings.agent_decision_contract_version] = provider
        return provider

    destination = run_experiment(
        experiment_id="mock-d1b",
        output_root=tmp_path,
        api_key="sentinel-api-key",
        discovered_model_id=MODEL,
        provider_factory=factory,
        require_clean_source=False,
    )
    assert providers[DIRECT_CONTRACT].calls == 85
    assert providers[SEMANTIC_CONTRACT].calls == 85
    assert artifact_set_complete(destination)
    assert set(artifact_hashes(destination)) == REQUIRED_FILES
    comparison = json.loads((destination / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["status"] == "COMPLETE"
    assert comparison["metadata"]["measured_attempts_total"] == 168
    serialized = "".join(path.read_text(encoding="utf-8") for path in destination.iterdir())
    assert "sentinel-api-key" not in serialized
    assert "Authorization" not in serialized
    assert '"customer_id"' not in serialized
