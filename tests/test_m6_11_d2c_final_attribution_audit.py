from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.m6_11_d2c_final_attribution_audit import (
    SOURCE_HASHES,
    SOURCE_ROOT,
    build_audit,
    canonical_audit_bytes,
    write_audit,
)
from evaluation.provenance import hash_prompt_bytes


def test_m6_11_attribution_counts_are_deterministic() -> None:
    audit = build_audit()
    assert audit.routing_mismatches == 324
    assert audit.resolver_failures == 132
    assert audit.unsafe_proposals == 18
    assert audit.routing_attribution_counts == {
        "genuine_model_semantic_failure": 41,
        "oracle_path_mismatch": 246,
        "valid_semantic_equivalent": 6,
        "wrong_intent": 31,
    }
    assert audit.resolver_attribution_counts == {
        "invalid_expectation": 34,
        "resolver_ineligible": 7,
        "upstream_clarification": 91,
    }
    assert audit.unsafe_attribution_counts == {"genuine_unsafe_semantic_decision": 18}
    assert audit.model_calls_performed == 0
    assert audit.historical_artifacts_changed is False


def test_m6_11_is_privacy_safe_and_has_no_deterministic_resolver_failure() -> None:
    audit = build_audit()
    assert all(value is False for value in audit.privacy.values())
    assert "genuine_resolver_failure" not in audit.resolver_attribution_counts
    assert audit.routing_attribution_counts.get("wrong_tool_route_mapping", 0) == 0
    assert all(record.evidence_codes for record in audit.routing_records)


def test_source_artifacts_are_immutable_and_report_is_non_overwriting(tmp_path: Path) -> None:
    audit = build_audit()
    destination = tmp_path / "m6_11_d2c_final_attribution_audit_v1.json"
    digest = write_audit(audit, destination)
    assert digest == hashlib.sha256(canonical_audit_bytes(audit)).hexdigest()
    with pytest.raises(FileExistsError):
        write_audit(audit, destination)
    for name, expected in SOURCE_HASHES.items():
        assert hash_prompt_bytes((SOURCE_ROOT / name).read_bytes()) == expected
