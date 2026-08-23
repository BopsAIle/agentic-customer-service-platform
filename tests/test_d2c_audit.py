from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.d2c_audit import (
    SOURCE_HASHES,
    SOURCE_ROOT,
    build_audit,
    canonical_audit_bytes,
    validate_source_artifacts,
    write_audit,
)
from evaluation.live_eval_v2 import live_eval_v2_cases


def test_d2c_audit_is_reproducible_and_covers_every_historical_failure() -> None:
    first = build_audit()
    second = build_audit()
    assert canonical_audit_bytes(first) == canonical_audit_bytes(second)
    assert first.routing_failures == 332
    assert first.resolver_failures == 145
    assert first.compiler_failures == 64
    assert sum(first.routing_attribution_counts.values()) == 332
    assert sum(first.resolver_attribution_counts.values()) == 145
    assert sum(first.compiler_attribution_counts.values()) == 64
    assert set(first.routing_attribution_counts) == {
        "wrong_intent",
        "valid_semantic_equivalent",
        "wrong_tool_mapping",
        "oracle_mismatch",
    }
    assert first.model_calls_performed == 0
    assert first.model_outputs_changed is False
    assert first.historical_artifacts_changed is False


def test_routing_attribution_separates_model_equivalence_and_oracle() -> None:
    audit = build_audit()
    valid_equivalents = [
        record
        for record in audit.routing_records
        if record.attribution == "valid_semantic_equivalent"
    ]
    assert len(valid_equivalents) == 6
    assert {record.pair_id for record in valid_equivalents} == {"std-subscription-question"}
    assert audit.routing_attribution_counts == {
        "oracle_mismatch": 257,
        "valid_semantic_equivalent": 6,
        "wrong_intent": 31,
        "wrong_tool_mapping": 38,
    }


def test_resolver_attribution_does_not_blame_ineligible_resolver_stage() -> None:
    audit = build_audit()
    assert audit.resolver_attribution_counts == {
        "expected_clarification": 90,
        "invalid_test_expectation": 49,
        "wrong_reference_from_model": 6,
    }
    assert "correct_reference_but_resolver_failure" not in audit.resolver_attribution_counts
    clarification = [
        record for record in audit.resolver_records if record.case_id == "d2c-en-amb-cancel-no-id"
    ]
    assert len(clarification) == 3
    assert {record.attribution for record in clarification} == {"expected_clarification"}
    fake_id = [
        record for record in audit.resolver_records if record.case_id == "d2c-en-adv-fake-order-id"
    ]
    assert {record.attribution for record in fake_id} == {"invalid_test_expectation"}


def test_compiler_attribution_preserves_fail_closed_and_unsupported_arguments() -> None:
    audit = build_audit()
    assert audit.compiler_attribution_counts == {
        "correct_fail_closed_clarification": 10,
        "incorrect_action_compilation": 36,
        "oracle_mismatch": 12,
        "unsupported_business_argument": 6,
    }
    unsupported = [
        record
        for record in audit.compiler_records
        if record.attribution == "unsupported_business_argument"
    ]
    assert len(unsupported) == 6
    assert all(record.root_owner == "model_semantics" for record in unsupported)
    oracle = [
        record for record in audit.compiler_records if record.attribution == "oracle_mismatch"
    ]
    assert {record.pair_id for record in oracle} == {
        "std-cancellation-explanation",
        "std-refund-eligibility",
    }


def test_audit_artifact_is_atomic_immutable_and_privacy_safe(tmp_path: Path) -> None:
    audit = build_audit()
    destination = tmp_path / "audit" / "d2c_attribution_audit_v1.json"
    digest = write_audit(audit, destination)
    content = destination.read_bytes()
    assert digest == hashlib.sha256(content).hexdigest()
    assert content == canonical_audit_bytes(audit)
    with pytest.raises(FileExistsError, match="already exists"):
        write_audit(audit, destination)
    for case in live_eval_v2_cases():
        for turn in case.interaction:
            assert turn.text.encode() not in content
    for prohibited in (
        b'"messages"',
        b'"prompt"',
        b'"arguments"',
        b'"order_id"',
        b'"ticket_id"',
        b"Authorization",
        b"OPENAI_API_KEY",
    ):
        assert prohibited not in content


def test_source_hash_mismatch_fails_closed_without_modifying_evidence(tmp_path: Path) -> None:
    copied = tmp_path / "source"
    copied.mkdir()
    for name in SOURCE_HASHES:
        (copied / name).write_bytes((SOURCE_ROOT / name).read_bytes())
    validate_source_artifacts(copied)
    (copied / "summary.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SOURCE_HASH_MISMATCH:summary.md"):
        validate_source_artifacts(copied)


def test_canonical_source_artifacts_remain_byte_identical() -> None:
    validate_source_artifacts()
    assert {
        name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest()
        for name in SOURCE_HASHES
    } == SOURCE_HASHES
