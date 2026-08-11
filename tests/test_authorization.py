from fastapi.testclient import TestClient

from app.main import app

TEST_CUSTOMER_ONE_TOKEN = "test-customer-one-token"


def _customer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_CUSTOMER_ONE_TOKEN}"}


def test_health_is_public_while_protected_route_requires_authentication(
    client: TestClient,
) -> None:
    with TestClient(app) as anonymous:
        health = anonymous.get("/health")
        protected = anonymous.get("/customers/1")

    assert health.status_code == 200
    assert protected.status_code == 401
    assert protected.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/customers/1",
        headers={"Authorization": "Bearer invalid-test-token"},
    )

    assert response.status_code == 401


def test_customer_can_access_own_customer_order_ticket_and_memory(
    client: TestClient,
) -> None:
    headers = _customer_headers()

    assert client.get("/customers/1", headers=headers).status_code == 200
    assert client.get("/orders/1", headers=headers).status_code == 200
    assert client.get("/tickets/1", headers=headers).status_code == 200
    assert client.get("/customers/1/memories", headers=headers).status_code == 200


def test_customer_cross_customer_access_is_not_found(client: TestClient) -> None:
    headers = _customer_headers()

    assert client.get("/customers/2", headers=headers).status_code == 404
    assert client.get("/orders/5", headers=headers).status_code == 404
    assert client.get("/tickets/2", headers=headers).status_code == 404
    assert client.get("/customers/2/memories", headers=headers).status_code == 404


def test_operator_can_access_ui_and_explicit_customer_scope(client: TestClient) -> None:
    assert client.get("/ui/system-health").status_code == 200
    assert client.get("/orders/1", params={"customer_id": 1}).status_code == 200
    assert client.get("/tickets/1", params={"customer_id": 1}).status_code == 200


def test_operator_resource_read_requires_explicit_customer_scope(client: TestClient) -> None:
    assert client.get("/orders/1").status_code == 400
    assert client.get("/tickets/1").status_code == 400


def test_customer_cannot_access_operator_ui(client: TestClient) -> None:
    response = client.get("/ui/system-health", headers=_customer_headers())

    assert response.status_code == 403


def test_customer_cannot_use_direct_business_write_routes(client: TestClient) -> None:
    headers = _customer_headers()

    cancellation = client.post(
        "/orders/3/cancel",
        json={"customer_id": 1},
        headers=headers,
    )
    refund = client.post(
        "/orders/2/refunds",
        json={"customer_id": 1, "reason": "Item arrived damaged."},
        headers=headers,
    )
    ticket = client.post(
        "/tickets",
        json={"customer_id": 1, "category": "account", "description": "Help needed."},
        headers=headers,
    )
    escalation = client.post(
        "/escalations",
        json={
            "customer_id": 1,
            "reason": "Customer requested an operator.",
            "priority": "high",
            "summary": "Needs review.",
        },
        headers=headers,
    )

    assert cancellation.status_code == 403
    assert refund.status_code == 403
    assert ticket.status_code == 403
    assert escalation.status_code == 403


def test_operator_can_use_direct_business_write_routes(client: TestClient) -> None:
    cancellation = client.post("/orders/3/cancel", json={"customer_id": 1})
    refund = client.post(
        "/orders/2/refunds",
        json={"customer_id": 1, "reason": "Item arrived damaged."},
    )

    assert cancellation.status_code == 200
    assert refund.status_code == 201


def test_customer_cannot_assert_another_customer_in_agent_chat(client: TestClient) -> None:
    response = client.post(
        "/agent/chat",
        json={
            "conversation_id": "cross-customer-http",
            "customer_id": 2,
            "message": "Show my orders",
        },
        headers=_customer_headers(),
    )

    assert response.status_code == 404
