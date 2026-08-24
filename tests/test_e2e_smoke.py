import pytest

from scripts.e2e_authenticated_smoke import (
    CONVERSATION_ID,
    EXPECTED_ACTOR_ID,
    SmokeFailure,
    assert_no_sensitive_projection_fields,
    assert_pending_response,
    assert_projection,
    redact,
)


def test_smoke_pending_contract_validates_server_owned_bindings() -> None:
    action_id = assert_pending_response(
        {
            "pending_action": {
                "action_id": "act_0123456789abcdef0123456789abcdef",
                "conversation_id": CONVERSATION_ID,
                "actor_id": EXPECTED_ACTOR_ID,
                "actor_type": "support_operator",
                "effective_customer_id": 2,
                "tool_name": "cancel_order",
                "arguments": {"customer_id": 2, "order_id": 3},
                "risk_level": 2,
                "status": "pending",
            }
        }
    )

    assert action_id == "act_0123456789abcdef0123456789abcdef"


def test_smoke_projection_rejects_missing_confirmation_metadata() -> None:
    with pytest.raises(SmokeFailure, match="confirmation-required policy outcome"):
        assert_projection(
            {
                "actor_id": EXPECTED_ACTOR_ID,
                "actor_type": "support_operator",
                "customer_id": 2,
                "conversation_id": CONVERSATION_ID,
                "path": ["check_pending_action"],
                "tools": [
                    {
                        "name": "cancel_order",
                        "risk_level": 2,
                        "status": "blocked_before_execution",
                    }
                ],
                "policy": [{"outcome": "allow"}],
            },
            confirmation_run=False,
        )


def test_smoke_diagnostics_redact_credentials() -> None:
    token = "integration-credential-must-not-leak"

    assert redact(f"before {token} after", token) == "before [REDACTED] after"


def test_smoke_projection_rejects_secret_bearing_fields() -> None:
    with pytest.raises(SmokeFailure, match="forbidden field"):
        assert_no_sensitive_projection_fields({"run_id": "safe", "token": "unsafe"})
