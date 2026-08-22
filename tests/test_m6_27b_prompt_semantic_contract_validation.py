from __future__ import annotations

from app.agent.semantic_attribution import RefundReasonSupportStatus
from evaluation.m6_27b_prompt_semantic_contract_validation import build_validation
from evaluation.provenance import prompt_path_for_contract


def test_semantic_prompt_states_authoritative_argument_provenance() -> None:
    prompt = " ".join(
        prompt_path_for_contract("semantic_decision_v3")
        .read_text(encoding="utf-8")
        .casefold()
        .split()
    )

    required_concepts = (
        "authoritative user-provided",
        "extract required arguments",
        "do not invent, infer, embellish, or paraphrase",
        "preserve the user's supported reason",
        "request clarification",
        "deterministic target resolution, validation, policy, confirmation, and execution",
    )
    for concept in required_concepts:
        assert concept in prompt


def test_prompt_does_not_authorize_bypassing_control_plane() -> None:
    prompt = " ".join(
        prompt_path_for_contract("semantic_decision_v3")
        .read_text(encoding="utf-8")
        .casefold()
        .split()
    )

    assert "bypass" not in prompt
    assert "confirmation-like phrase does not authorize" in prompt
    assert "application performs deterministic" in prompt


def test_prompt_contract_fixtures_preserve_runtime_and_provenance_behavior() -> None:
    validation = build_validation()
    observations = {item.fixture_id: item for item in validation.fixtures}

    for fixture_id in ("supported-turkish-refund", "supported-english-refund"):
        item = observations[fixture_id]
        assert item.refund_reason_support_status == RefundReasonSupportStatus.SUPPORTED
        assert item.compiler == "action"
        assert item.policy == "confirmation_required"
        assert item.pending_action is True
        assert item.risk_level == 2

    assert observations["missing-refund-reason"].refund_reason_support_status == (
        RefundReasonSupportStatus.MISSING
    )
    for fixture_id in ("unsupported-refund-reason", "unsupported-refund-embellishment"):
        assert observations[fixture_id].refund_reason_support_status == (
            RefundReasonSupportStatus.UNSUPPORTED
        )
        assert observations[fixture_id].outcome == "clarification"

    assert observations["supported-turkish-multi-turn-refund"].compiler == "action"
    assert observations["safe-read"].outcome == "read"
    assert observations["cancellation-write"].outcome == "action"


def test_prompt_fixture_validation_is_not_a_persisted_raw_payload() -> None:
    serialized = build_validation().model_dump_json()

    for prohibited in ("hasarlı", "damaged", "changed my mind", "customer_id", "order_id"):
        assert prohibited not in serialized
