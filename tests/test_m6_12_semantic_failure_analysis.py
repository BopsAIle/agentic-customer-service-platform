from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.m6_12_semantic_failure_analysis import (
    M6_10_ARTIFACT_HASHES,
    M6_10_ROOT,
    build_analysis,
    canonical_bytes,
    write_analysis,
)
from evaluation.provenance import hash_prompt_bytes


def test_m6_12_counts_and_recommendation_are_frozen() -> None:
    analysis = build_analysis()
    assert analysis.genuine_model_semantic_failures == 41
    assert analysis.genuine_unsafe_semantic_proposals == 18
    assert [group.count for group in analysis.semantic_failure_groups] == [30, 4, 6, 1]
    assert [group.count for group in analysis.unsafe_proposal_groups] == [12, 6]
    assert analysis.recommendation == "REQUIRE_SEMANTIC_DECISION_V3_IMPROVEMENT_FIRST"
    assert analysis.model_calls_performed == 0


def test_m6_12_is_privacy_safe_and_uses_case_ids_only() -> None:
    analysis = build_analysis()
    assert all(value is False for value in analysis.privacy.values())
    assert all(
        all(" " not in case_id for case_id in group.representative_case_ids)
        for group in (*analysis.semantic_failure_groups, *analysis.unsafe_proposal_groups)
    )


def test_m6_12_artifact_is_immutable_and_source_hashes_are_pinned(tmp_path: Path) -> None:
    analysis = build_analysis()
    destination = tmp_path / "m6_12_semantic_failure_analysis_v1.json"
    digest = write_analysis(analysis, destination)
    assert digest == hashlib.sha256(canonical_bytes(analysis)).hexdigest()
    with pytest.raises(FileExistsError):
        write_analysis(analysis, destination)
    for name, expected in M6_10_ARTIFACT_HASHES.items():
        assert hash_prompt_bytes((M6_10_ROOT / name).read_bytes()) == expected
