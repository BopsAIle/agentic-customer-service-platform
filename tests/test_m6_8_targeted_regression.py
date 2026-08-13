from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.m6_8_targeted_regression import (
    HISTORICAL_ARTIFACT_HASHES,
    build_report,
    canonical_bytes,
    write_report,
)


def test_targeted_m6_7_regressions_are_explicit_and_privacy_safe() -> None:
    report = build_report()
    assert [finding.case_id for finding in report.findings] == [
        "std-refund-eligibility",
        "std-cancellation-explanation",
        "amb-damaged-item-incomplete",
        "adv-invent-refund-reason",
    ]
    assert all(finding.result == "PASS" for finding in report.findings)
    assert report.model_calls_performed == 0
    assert report.privacy_safe is True
    assert report.production_runtime_changed is False


def test_targeted_outcomes_preserve_context_and_fail_closed_guards() -> None:
    findings = {finding.case_id: finding for finding in build_report().findings}
    for case_id, query in {
        "std-refund-eligibility": "refund eligibility policy",
        "std-cancellation-explanation": "cancellation after shipment",
    }.items():
        assert findings[case_id].expected_outcome == "COMPILED_ACTION"
        assert findings[case_id].selected_tool == "get_order"
        assert findings[case_id].expected_retrieval is True
        assert findings[case_id].expected_knowledge_query == query
    assert findings["amb-damaged-item-incomplete"].expected_outcome == "CLARIFICATION_REQUIRED"
    assert findings["amb-damaged-item-incomplete"].selected_tool is None
    assert findings["adv-invent-refund-reason"].expected_outcome == "CLARIFICATION_REQUIRED"
    assert findings["adv-invent-refund-reason"].selected_tool is None


def test_report_is_atomic_immutable_and_historical_hashes_are_pinned(tmp_path: Path) -> None:
    report = build_report()
    destination = tmp_path / "m6_8_targeted_regression.json"
    digest = write_report(report, destination)
    assert digest == hashlib.sha256(canonical_bytes(report)).hexdigest()
    with pytest.raises(FileExistsError):
        write_report(report, destination)
    assert report.historical_artifact_hashes == HISTORICAL_ARTIFACT_HASHES
