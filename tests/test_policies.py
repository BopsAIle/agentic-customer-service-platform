from datetime import UTC, datetime, timedelta

import pytest

from app.policies.confirmation import is_expired, parse_confirmation
from app.policies.engine import PolicyEngine
from app.policies.models import PendingAction, PolicyOutcome


@pytest.mark.parametrize("value", ["yes", "YES", " confirm ", "proceed", "do it"])
def test_confirmation_parser_accepts_bounded_confirmations(value: str) -> None:
    assert parse_confirmation(value) == "confirmed"


@pytest.mark.parametrize("value", ["no", "cancel", "never mind", "don't do it"])
def test_confirmation_parser_accepts_bounded_rejections(value: str) -> None:
    assert parse_confirmation(value) == "rejected"


def test_confirmation_parser_rejects_ambiguous_substitution_text() -> None:
    assert parse_confirmation("yes, and refund order 999") == "ambiguous"


def test_policy_engine_applies_registry_risk_deterministically() -> None:
    engine = PolicyEngine()
    assert (
        engine.evaluate(
            tool_name="get_order", customer_id=1, arguments={"customer_id": 1, "order_id": 2}
        ).outcome
        == PolicyOutcome.ALLOW
    )
    assert (
        engine.evaluate(
            tool_name="cancel_order", customer_id=1, arguments={"customer_id": 1, "order_id": 3}
        ).outcome
        == PolicyOutcome.REQUIRE_CONFIRMATION
    )
    assert (
        engine.evaluate(
            tool_name="escalate_to_human", customer_id=1, arguments={"customer_id": 1}
        ).outcome
        == PolicyOutcome.REQUIRE_HUMAN
    )


def test_policy_engine_denies_unknown_or_wrong_customer() -> None:
    engine = PolicyEngine()
    unknown = engine.evaluate(tool_name="not_registered", customer_id=1, arguments={})
    wrong_customer = engine.evaluate(
        tool_name="cancel_order", customer_id=1, arguments={"customer_id": 2, "order_id": 3}
    )
    assert unknown.outcome == PolicyOutcome.DENY
    assert "unknown_tool" in unknown.reasons
    assert wrong_customer.outcome == PolicyOutcome.DENY
    assert "ownership_required" in wrong_customer.reasons


def test_expiration_is_clock_driven() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    action = PendingAction(
        action_id="act_test",
        conversation_id="conv_test",
        customer_id=1,
        tool_name="cancel_order",
        arguments={"customer_id": 1, "order_id": 3},
        risk_level=2,
        created_at=created,
    )
    assert not is_expired(action, created + timedelta(seconds=299), 300)
    assert is_expired(action, created + timedelta(seconds=300), 300)
