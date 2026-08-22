from __future__ import annotations

import json

from evaluation.d2d_spec import (
    D2D_ALEMBIC_HEAD,
    D2D_ARTIFACT_SCHEMA_VERSION,
    D2D_CONTRACT_SHA256,
    D2D_CONTRACT_VERSION,
    D2D_FAULT_MATRIX_SHA256,
    D2D_SCHEDULE_SHA256,
    D2dContract,
    canonical_d2d_contract,
    d2d_contract_sha256,
    d2d_fault_matrix_sha256,
    d2d_schedule_sha256,
    validate_contract_identity,
)


def test_d2d_contract_identity_is_frozen_and_deterministic() -> None:
    contract = canonical_d2d_contract()

    validate_contract_identity(contract)

    assert contract.contract_version == D2D_CONTRACT_VERSION
    assert d2d_contract_sha256(contract) == D2D_CONTRACT_SHA256
    assert d2d_schedule_sha256(contract) == D2D_SCHEDULE_SHA256
    assert d2d_fault_matrix_sha256(contract) == D2D_FAULT_MATRIX_SHA256
    assert d2d_contract_sha256(canonical_d2d_contract()) == D2D_CONTRACT_SHA256


def test_d2d_phases_and_operational_scenarios_are_complete() -> None:
    contract = canonical_d2d_contract()

    assert len(contract.phases) == 8
    assert len(contract.scenarios) == 18
    assert all(phase.mandatory for phase in contract.phases)
    assert all(scenario.mandatory for scenario in contract.scenarios)
    assert {scenario.execution_mode for scenario in contract.scenarios} == {
        "EXISTING_INTERFACE",
        "HARNESS_REQUIRED",
    }


def test_d2d_concurrency_is_correctness_only_and_frozen() -> None:
    concurrency = canonical_d2d_contract().concurrency

    assert concurrency == {
        "same_action_concurrent_attempts": 16,
        "same_action_rounds": 3,
        "same_action_success_invariant": (
            "exactly_one_committed_business_effect_per_round; all_other_contenders resolve safely"
        ),
        "independent_action_count": 2,
        "independent_action_rounds": 3,
        "capacity_or_throughput_claim": False,
    }


def test_d2d_is_provider_independent_and_configuration_hermetic() -> None:
    contract = canonical_d2d_contract()

    assert contract.provider_requirement == "NOT_APPLICABLE_CORE"
    assert contract.environment["openai_model_list_calls"] == 0
    assert contract.environment["openai_inference_calls"] == 0
    assert contract.environment["ambient_dotenv"] == (
        "ignored; dedicated frozen environment required"
    )
    assert contract.environment["alembic_head"] == D2D_ALEMBIC_HEAD


def test_d2d_retry_artifact_and_zero_tolerance_contracts_are_fail_closed() -> None:
    contract = canonical_d2d_contract()

    assert contract.retry_policy == {
        "per_test_automatic_retry_count": 0,
        "automatic_full_run_rerun_count": 0,
        "patch_and_continue": False,
        "invalid_run_requires_new_approval": True,
    }
    assert contract.artifact_schema_version == D2D_ARTIFACT_SCHEMA_VERSION
    assert contract.artifact_contract["files"] == (
        "manifest.json",
        "environment.json",
        "attempts.json",
        "summary.json",
        "summary.md",
    )
    assert len(contract.zero_tolerance_failures) == 15
    assert "privacy_violation" in contract.zero_tolerance_failures
    assert "same_action_multiple_committed_effects" in contract.zero_tolerance_failures


def test_d2d_non_goals_do_not_become_release_gate_scenarios() -> None:
    contract = canonical_d2d_contract()
    scenario_ids = {scenario.scenario_id for scenario in contract.scenarios}

    assert "large-scale throughput certification" in contract.non_goals
    assert "exact provider cost accounting" in contract.non_goals
    assert "multi-region operation" in contract.non_goals
    assert "load-test" not in scenario_ids
    assert contract.scope_decisions["full_load_benchmarking"] == "POST_RC_HARDENING"
    assert contract.scope_decisions["exact_llm_cost_accounting"] == (
        "NON_BLOCKING_POST_RC_HARDENING"
    )


def test_d2d_future_approval_bindings_cover_execution_identity() -> None:
    bindings = set(canonical_d2d_contract().approval_bindings)

    assert {
        "experiment_id",
        "exact source revision",
        "d2d contract version and SHA",
        "environment/configuration identity",
        "Alembic head",
        "scenario schedule SHA",
        "concurrency parameters",
        "fault matrix identity",
        "artifact schema/version",
        "retry and rerun policy",
    } <= bindings


def test_d2d_contract_serialization_is_json_safe_without_provider_side_effects() -> None:
    payload = canonical_d2d_contract().model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert "OPENAI_API_KEY" not in serialized
    assert "Authorization" not in serialized
    assert "raw user text, raw model payloads" in serialized.casefold()
    assert "chain-of-thought" not in serialized.casefold()
    assert D2dContract.model_validate_json(serialized).contract_version == D2D_CONTRACT_VERSION
