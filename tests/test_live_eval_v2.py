from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluation.d2c_oracle import LiveEvalV2Decision, canonical_live_eval_v2_decision
from evaluation.live_eval_v2 import (
    D2C_SCHEDULE_VERSION,
    LIVE_EVAL_V2_SCHEMA_VERSION,
    LIVE_EVAL_V2_VERSION,
    D2cScenario,
    d2c_schedule,
    d2c_schedule_hash,
    live_eval_v2_cases,
    live_eval_v2_hash,
)

EXPECTED_DATASET_HASH = "1a4844e843a49cd01083adc81330398206dde4b6b4c3a4c42b0d4228a8d1556b"
EXPECTED_SCHEDULE_HASH = "9b2cd9fa10bd9279dc0d0b3de11aebd383c1cd6e12ab42733a802e281efd26fe"
EXPECTED_DECISION_HASH = "e72412c1d8afc47b62627fcf089b827b5012883ec9cfb36402ddba7a29228def"


def test_live_eval_v2_has_frozen_counts_and_unique_required_fields() -> None:
    cases = live_eval_v2_cases()

    assert len(cases) == len({case.case_id for case in cases}) == 180
    assert Counter(case.language for case in cases) == {"en": 90, "tr": 90}
    assert Counter(case.category for case in cases) == {
        "standard": 48,
        "ambiguity": 32,
        "adversarial": 40,
        "multi_turn": 36,
        "failure_recovery": 24,
    }
    assert all(case.schema_version == LIVE_EVAL_V2_SCHEMA_VERSION for case in cases)
    assert all(case.interaction for case in cases)
    assert all(case.semantic.accepted_intents for case in cases)
    assert all(case.semantic.accepted_request_types for case in cases)
    assert all(case.semantic.accepted_target_variants for case in cases)
    assert all(case.deterministic.accepted_execution_paths for case in cases)


def test_live_eval_v2_pairs_preserve_oracle_and_interaction_shape() -> None:
    by_pair: dict[str, list[D2cScenario]] = {}
    for case in live_eval_v2_cases():
        by_pair.setdefault(case.pair_id, []).append(case)

    assert len(by_pair) == 90
    for paired in by_pair.values():
        assert [case.language for case in paired] == ["en", "tr"]
        english, turkish = paired
        assert english.category == turkish.category
        assert english.semantic == turkish.semantic
        assert english.safety == turkish.safety
        assert english.deterministic == turkish.deterministic
        assert english.failure_injection == turkish.failure_injection
        for case in paired:
            assert [turn.sequence for turn in case.interaction] == list(
                range(1, len(case.interaction) + 1)
            )


def test_live_eval_v2_is_synthetic_and_contains_no_expected_answer_or_reasoning_fields() -> None:
    serialized = json.dumps(
        [case.model_dump(mode="json") for case in live_eval_v2_cases()],
        ensure_ascii=False,
    )

    for prohibited_field in (
        '"assistant"',
        '"expected_answer"',
        '"hidden_reasoning"',
        '"chain_of_thought"',
        '"credential"',
        '"authorization"',
        '"api_key"',
    ):
        assert prohibited_field not in serialized.lower()
    assert {case.customer_fixture for case in live_eval_v2_cases()} == {"customer_1"}


def test_live_eval_v2_hash_and_schedule_are_deterministic() -> None:
    cases = live_eval_v2_cases()
    schedule = d2c_schedule(cases)

    assert LIVE_EVAL_V2_VERSION == "live_eval_v2"
    assert live_eval_v2_hash(cases) == live_eval_v2_hash() == EXPECTED_DATASET_HASH
    assert D2C_SCHEDULE_VERSION == "d2c_case_major_repetition_v1"
    assert len(schedule) == 540
    assert [entry.ordinal for entry in schedule] == list(range(1, 541))
    assert schedule[0].case_id == "d2c-en-std-order-status-explicit"
    assert schedule[0].repetition == 1
    assert schedule[-1].case_id == "d2c-tr-fail-checkpoint-persistence"
    assert schedule[-1].repetition == 3
    assert d2c_schedule_hash(schedule) == d2c_schedule_hash() == EXPECTED_SCHEDULE_HASH
    repetitions = Counter(entry.case_id for entry in schedule)
    assert set(repetitions.values()) == {3}


def test_live_eval_v2_failure_injections_are_deterministic_and_category_scoped() -> None:
    cases = live_eval_v2_cases()

    failure_cases = [case for case in cases if case.category == "failure_recovery"]
    assert len(failure_cases) == 24
    assert all(case.failure_injection.kind != "none" for case in failure_cases)
    assert all(case.failure_injection.deterministic_only for case in failure_cases)
    assert all(
        case.failure_injection.kind == "none"
        for case in cases
        if case.category != "failure_recovery"
    )


def test_live_eval_v2_decision_artifact_matches_canonical_record() -> None:
    path = Path("evaluation/decisions/live_eval_v2_decision.json")
    tracked = LiveEvalV2Decision.model_validate_json(path.read_text(encoding="utf-8"))

    assert tracked == canonical_live_eval_v2_decision()
    assert tracked.status == "FROZEN_NOT_APPROVED_FOR_EXECUTION"
    assert tracked.dataset["sha256"] == EXPECTED_DATASET_HASH
    assert tracked.schedule["sha256"] == EXPECTED_SCHEDULE_HASH
    assert tracked.execution_authorized is False
    assert tracked.model_calls_performed == 0
    assert tracked.benchmark_artifacts_generated is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_DECISION_HASH
