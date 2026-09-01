from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.m6_6_clarification_audit import (
    BASELINE_HASHES,
    BASELINE_ROOT,
    CURRENT_HASHES,
    CURRENT_ROOT,
    build_audit,
    canonical_bytes,
    write_audit,
)
from evaluation.provenance import hash_prompt_bytes


def test_clarification_delta_is_exact_and_privacy_safe() -> None:
    audit = build_audit()
    assert audit.baseline_clarification_correct == 480
    assert audit.current_clarification_correct == 473
    assert audit.clarification_delta == -7
    assert audit.affected_attempts == 13
    assert audit.classification_counts == {
        "correct_action_after_compiler_fix": 3,
        "incorrect_loss_of_clarification": 2,
        "oracle_mismatch": 6,
        "unrelated_behavior_change": 2,
    }
    assert all(value is False for value in audit.privacy.values())
    assert audit.model_calls_performed == 0


def test_affected_scenarios_are_explicit() -> None:
    audit = build_audit()
    assert {record.pair_id for record in audit.records} == {
        "std-refund-eligibility",
        "std-cancellation-explanation",
        "amb-order-status-no-id",
        "amb-refund-no-reason",
        "amb-memory-value-missing",
        "amb-escalation-reason-missing",
        "amb-damaged-item-incomplete",
        "adv-other-customer-ticket",
        "adv-invent-refund-reason",
    }


def test_sources_are_immutable_and_writer_refuses_overwrite(tmp_path: Path) -> None:
    audit = build_audit()
    destination = tmp_path / "m6_6.json"
    digest = write_audit(audit, destination)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert destination.read_bytes() == canonical_bytes(audit)
    with pytest.raises(FileExistsError):
        write_audit(audit, destination)
    for name, expected in BASELINE_HASHES.items():
        root = BASELINE_ROOT
        assert hash_prompt_bytes((root / name).read_bytes()) == expected
    for name, expected in CURRENT_HASHES.items():
        root = CURRENT_ROOT
        assert hash_prompt_bytes((root / name).read_bytes()) == expected
