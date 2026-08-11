from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_customer_lookup(client: TestClient) -> None:
    response = client.get("/customers/1")
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


def test_missing_customer(client: TestClient) -> None:
    response = client.get("/customers/999")
    assert response.status_code == 404


def test_order_lookup(client: TestClient) -> None:
    response = client.get("/orders/1")
    assert response.status_code == 200
    assert response.json()["status"] == "shipped"


def test_customer_orders(client: TestClient) -> None:
    response = client.get("/customers/1/orders")
    assert response.status_code == 200
    assert len(response.json()) == 4


def test_ticket_lookup(client: TestClient) -> None:
    response = client.get("/tickets/1")
    assert response.status_code == 200
    assert response.json()["category"] == "delivery"


def test_missing_ticket(client: TestClient) -> None:
    response = client.get("/tickets/999")
    assert response.status_code == 404


def test_create_ticket_endpoint(client: TestClient) -> None:
    response = client.post(
        "/tickets",
        json={
            "customer_id": 1,
            "order_id": 3,
            "category": "delivery",
            "description": "Can I change the delivery address?",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_cancel_and_refund_endpoints(client: TestClient) -> None:
    cancel_response = client.post("/orders/3/cancel", json={"customer_id": 1})
    refund_response = client.post(
        "/orders/2/refunds",
        json={"customer_id": 1, "reason": "Item arrived damaged."},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["changed"] is True
    assert refund_response.status_code == 201
    assert refund_response.json()["status"] == "requested"


def test_escalation_endpoint(client: TestClient) -> None:
    response = client.post(
        "/escalations",
        json={
            "customer_id": 1,
            "ticket_id": 1,
            "reason": "Customer requested an operator.",
            "priority": "high",
            "summary": "Delivery issue needs human review.",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "queued"
