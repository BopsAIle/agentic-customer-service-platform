from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.d2c_compiler_audit import (
    ATTRIBUTION_AUDIT_NAME,
    ATTRIBUTION_AUDIT_SHA256,
    CLASSIFICATIONS,
    SOURCE_ARTIFACT_HASHES,
    SOURCE_EVIDENCE_ROOT,
    build_audit,
    canonical_audit_bytes,
    write_audit,
)
from evaluation.provenance import hash_prompt_bytes


def test_audit_classifies_all_targeted_failures() -> None:
    audit = build_audit()

    assert audit.analyzed_incorrect_action_compilation == 36
    assert audit.analyzed_compiler_oracle_mismatches == 12
    assert audit.analyzed_total == 48
    assert audit.classification_counts == {
        "model_semantic_decision_incorrect": 36,
        "compiler_mapping_missing": 12,
        "correct_fail_closed_behavior": 0,
        "oracle_expectation_mismatch": 0,
        "unsupported_business_argument_handling": 0,
    }
    assert set(audit.classification_counts) == set(CLASSIFICATIONS)


def test_hybrid_state_plus_policy_failures_are_missing_compiler_mapping() -> None:
    audit = build_audit()
    records = [
        record for record in audit.records if record.classification == "compiler_mapping_missing"
    ]

    assert len(records) == 12
    assert {record.pair_id for record in records} == {
        "std-refund-eligibility",
        "std-cancellation-explanation",
    }
    assert {record.language for record in records} == {"en", "tr"}
    assert {record.actual_compiler_outcome for record in records} == {"knowledge"}
    assert {record.expected_compiler_outcome for record in records} == {"action"}
    assert all(
        any(path.startswith("get_order_then_retrieve_") for path in record.expected_execution_paths)
        for record in records
    )


def test_other_action_compilation_failures_belong_to_model_semantics() -> None:
    audit = build_audit()
    records = [
        record
        for record in audit.records
        if record.classification == "model_semantic_decision_incorrect"
    ]

    assert len(records) == 36
    assert {record.pair_id for record in records} == {
        "amb-order-status-no-id",
        "amb-damaged-item-incomplete",
        "amb-contradictory-cancel",
        "adv-prompt-reveal",
        "adv-rag-injection",
        "mt-decline-confirmation",
        "mt-stale-confirmation",
    }
    assert all(record.root_owner == "model_semantics" for record in records)
    assert all(
        {
            record.actual_intent not in record.accepted_intents,
            record.actual_request_type not in record.accepted_request_types,
            record.actual_clarification != record.expected_clarification,
        }
        != {False}
        for record in records
    )


def test_audit_is_deterministic_and_privacy_safe() -> None:
    first = canonical_audit_bytes(build_audit())
    second = canonical_audit_bytes(build_audit())
    payload = json.loads(first)

    assert first == second
    assert payload["model_calls_performed"] == 0
    assert payload["model_outputs_changed"] is False
    assert payload["historical_artifacts_changed"] is False
    assert payload["production_runtime_changed"] is False
    assert all(value is False for value in payload["privacy"].values())
    forbidden_keys = {
        "message",
        "messages",
        "prompt",
        "reasoning",
        "arguments",
        "raw_payload",
        "order_id",
        "ticket_id",
        "authorization",
        "api_key",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    privacy_declaration = payload.pop("privacy")
    assert keys(payload).isdisjoint(forbidden_keys)
    assert privacy_declaration["reasoning"] is False


def test_source_evidence_identity_is_frozen() -> None:
    audit = build_audit()

    assert audit.source_artifact_sha256 == SOURCE_ARTIFACT_HASHES
    assert audit.source_attribution_audit_sha256 == ATTRIBUTION_AUDIT_SHA256
    assert (
        hash_prompt_bytes(
            (SOURCE_EVIDENCE_ROOT / "audit" / ATTRIBUTION_AUDIT_NAME).read_bytes()
        )
        == ATTRIBUTION_AUDIT_SHA256
    )
    for name, expected in SOURCE_ARTIFACT_HASHES.items():
        assert hash_prompt_bytes((SOURCE_EVIDENCE_ROOT / name).read_bytes()) == expected


def test_attribution_source_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in SOURCE_ARTIFACT_HASHES:
        (source / name).write_bytes((SOURCE_EVIDENCE_ROOT / name).read_bytes())
    audit_dir = source / "audit"
    audit_dir.mkdir()
    (audit_dir / ATTRIBUTION_AUDIT_NAME).write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="D2C_COMPILER_AUDIT_ATTRIBUTION_SOURCE_HASH_MISMATCH"):
        build_audit(source)


def test_atomic_writer_refuses_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "audit.json"
    audit = build_audit()

    digest = write_audit(audit, destination)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert destination.read_bytes() == canonical_audit_bytes(audit)
    with pytest.raises(FileExistsError, match="already exists"):
        write_audit(audit, destination)
