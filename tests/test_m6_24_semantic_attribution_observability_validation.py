from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent.semantic_attribution import (
    CompilerClarificationCause,
    RefundReasonSupportStatus,
)
from evaluation.m6_24_semantic_attribution_observability_validation import (
    build_validation,
    canonical_bytes,
    write_validation,
)


def test_attribution_fixtures_distinguish_model_and_compiler_clarification() -> None:
    validation = build_validation()
    observations = {item.fixture_id: item for item in validation.fixtures}

    model = observations["model-level-clarification"]
    assert model.semantic_requested_clarification is True
    assert model.refund_reason_support_status == RefundReasonSupportStatus.NOT_APPLICABLE
    assert model.compiler_clarification_cause == CompilerClarificationCause.OTHER

    missing = observations["missing-refund-reason"]
    assert missing.semantic_requested_clarification is False
    assert missing.required_refund_reason_present is False
    assert missing.refund_reason_support_status == RefundReasonSupportStatus.MISSING
    assert missing.compiler_clarification_cause == CompilerClarificationCause.MISSING_REFUND_REASON

    unsupported = observations["unsupported-refund-reason"]
    assert unsupported.semantic_requested_clarification is False
    assert unsupported.required_refund_reason_present is True
    assert unsupported.refund_reason_support_status == RefundReasonSupportStatus.UNSUPPORTED
    assert (
        unsupported.compiler_clarification_cause
        == CompilerClarificationCause.UNSUPPORTED_REFUND_REASON
    )


def test_supported_english_turkish_and_overlap_fixtures_preserve_behavior() -> None:
    validation = build_validation()
    observations = {item.fixture_id: item for item in validation.fixtures}

    for fixture_id in ("supported-english-refund-reason", "supported-turkish-refund-reason"):
        item = observations[fixture_id]
        assert item.refund_reason_support_status == RefundReasonSupportStatus.SUPPORTED
        assert item.executable_action is True
        assert item.actual_policy == "confirmation_required"

    overlap = observations["accidental-lexical-overlap"]
    assert overlap.refund_reason_support_status == RefundReasonSupportStatus.UNSUPPORTED
    assert overlap.executable_action is False

    read = observations["safe-non-refund-read"]
    assert read.refund_reason_support_status == RefundReasonSupportStatus.NOT_APPLICABLE
    assert read.required_refund_reason_present is None

    valid_tr = observations["valid-turkish-refund-runtime"]
    assert valid_tr.pending_action is True
    assert valid_tr.risk_level == 2


def test_validation_artifact_is_atomic_and_privacy_safe(tmp_path: Path) -> None:
    validation = build_validation()
    destination = tmp_path / "m6_24.json"
    digest = write_validation(validation, destination)
    content = destination.read_bytes()

    assert digest == hashlib.sha256(canonical_bytes(validation)).hexdigest()
    assert json.loads(content)
    assert content == canonical_bytes(validation)
    for prohibited in (
        b"hasarl",
        b"damaged",
        b"changed my mind",
        b"para iadesi",
        b"customer_id",
        b"order_id",
        b"messages",
        b"prompt",
    ):
        assert prohibited not in content
    assert b'"bounded_fields_only": true' in content
