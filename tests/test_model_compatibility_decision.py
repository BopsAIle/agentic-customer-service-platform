from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from evaluation.model_compatibility_matrix import Eligibility, eligibility_for

DECISION_PATH = Path("evaluation/decisions/model_compatibility_d2a_v1.json")


def _decision() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(DECISION_PATH.read_text(encoding="utf-8")))


def test_d2a_decision_freezes_exact_contract_dataset_and_candidates() -> None:
    decision = _decision()
    assert decision["status"] == "ACCEPTED"
    assert decision["contract"] == {
        "version": "semantic_decision_v3",
        "schema_hash": ("b0c7c1ddb1fe4423b528f7ce05fbc63fa117737c797149f5903d327a8de6280b"),
        "function_schema_hash": (
            "49ad87926db3b66c183000da65f528008b2021d0c040e76218a5e4c3318d2fc1"
        ),
        "prompt_hash": ("4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0"),
        "structured_output_mode": "function_calling",
    }
    assert decision["dataset"]["version"] == "live_eval_v1_2"
    assert (
        decision["dataset"]["targeted_subset_hash"]
        == (decision["dataset"]["historical_v1_1_subset_hash"])
    )
    assert [item["model"] for item in decision["candidates"]] == [
        "gpt-5.6-luna",
        "qwen3.5:4b",
        "qwen2.5:7b-instruct",
        "qwen3.5:9b",
    ]


def test_d2a_decision_eligibility_is_rederived_from_preregistered_rules() -> None:
    decision = _decision()
    for candidate in decision["candidates"]:
        taxonomy = {
            "normalized_errors": candidate["failure_taxonomy"]["normalized_errors"],
            "transport_failures": 0,
            "argument_decode_failures": 0,
        }
        actual = eligibility_for(
            provider_success=candidate["provider_success"],
            arguments_decoded=candidate["arguments_decoded"],
            typed_success=candidate["typed_semantic_decision_v3"],
            timeout_count=candidate["timeouts"],
            failure_taxonomy=taxonomy,
        )
        assert actual.value == candidate["eligibility"]
    assert decision["decision"]["d2b_eligible_candidates"] == ["gpt-5.6-luna"]
    assert decision["decision"]["d2b_review_candidates"] == []


def test_d2a_decision_records_complete_immutable_artifact_hashes() -> None:
    decision = _decision()
    for candidate in decision["candidates"]:
        assert set(candidate["artifacts"]) == {
            "attempts.json",
            "summary.json",
            "summary.md",
        }
        assert all(len(value) == 64 for value in candidate["artifacts"].values())
    assert decision["decision"]["model_calls_during_freeze"] == 0
    assert decision["decision"]["production_defaults_changed"] is False


def test_d2a_decision_does_not_overclaim_local_model_quality() -> None:
    markdown = Path("docs/model-compatibility-decision.md").read_text(encoding="utf-8")
    normalized = " ".join(markdown.split())
    assert "do not show that the model families are universally incompatible" in normalized
    assert "not an automatic production-model selection" in normalized
    assert "At the D2a decision date, `direct_tool_v1` remained" in normalized
    assert "M6.73 later changed the runnable default" in normalized
    assert Eligibility.ELIGIBLE.value in DECISION_PATH.read_text(encoding="utf-8")
