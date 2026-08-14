from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.m6_14_semantic_guard_validation import (
    M6_10_HASHES,
    build_validation,
    canonical_bytes,
    write_validation,
)


def test_m6_14_targeted_validation_contains_all_known_shapes() -> None:
    validation = build_validation()
    assert len(validation.findings) == 10
    assert validation.known_semantic_error_attempts == 41
    assert validation.known_unsafe_proposal_attempts == 18
    assert validation.model_semantic_errors_still_emitted == 41
    assert validation.safely_contained_by_runtime == 41
    assert validation.unsafe_executable_proposals_after_guards == 0
    assert validation.prompt_gate == "DETERMINISTIC_GUARDS_SUFFICIENT_FOR_PROSPECTIVE_VALIDATION"


def test_m6_14_preserves_contract_and_privacy() -> None:
    validation = build_validation()
    assert validation.semantic_schema_changed is False
    assert validation.function_schema_changed is False
    assert validation.prompt_changed is False
    assert validation.prompt_hash_unchanged is True
    assert all(value is False for value in validation.privacy.values())
    assert all(finding.result == "PASS" for finding in validation.findings)


def test_m6_14_report_is_immutable_and_source_hashes_are_pinned(tmp_path: Path) -> None:
    validation = build_validation()
    destination = tmp_path / "m6_14_semantic_guard_validation_v1.json"
    digest = write_validation(validation, destination)
    assert digest == hashlib.sha256(canonical_bytes(validation)).hexdigest()
    with pytest.raises(FileExistsError):
        write_validation(validation, destination)
    assert set(M6_10_HASHES) == {
        "manifest.json",
        "attempts.json",
        "summary.json",
        "summary.md",
    }
    assert all(len(expected) == 64 for expected in M6_10_HASHES.values())
