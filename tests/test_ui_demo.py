from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_demo_scenarios_are_bounded_read_only_projections(client: TestClient) -> None:
    response = client.get("/ui/demo-scenarios")

    assert response.status_code == 200
    payload = response.json()
    assert [item["scenario_id"] for item in payload] == [
        "refund-memory-rag",
        "prompt-injection-defense",
        "duplicate-operation-protection",
        "missing-information-clarification",
    ]
    serialized = json.dumps(payload, sort_keys=True)
    assert "raw_provider_response" not in serialized
    assert "chain_of_thought" not in serialized
    assert "api_key" not in serialized
    assert all(item["run"]["execution_mode"] == "recorded_replay" for item in payload)
    assert all(item["run"]["provider"] == "recorded_demo" for item in payload)
    assert all(5 <= len(item["messages"]) <= 8 for item in payload)


def test_refund_demo_contains_context_and_confirmation_boundary(client: TestClient) -> None:
    payload = client.get("/ui/demo-scenarios").json()[0]
    run = payload["run"]

    assert payload["messages"]
    assert run["memory"]["retrieved_count"] == 1
    assert run["rag_documents"][0]["grounding_status"] == "validated"
    assert run["rag_documents"][0]["citation_preview"]
    assert run["proposal"]["validation"] == "passed"
    assert run["evidence"]["compiler"]["status"] == "passed"
    assert run["policy"][0]["outcome"] == "require_confirmation"
    assert run["evidence"]["write_outcome"]["status"] == "pending_confirmation"
    assert run["status"] == "waiting_confirmation"


def test_demo_scenarios_include_observable_boundary_transitions(client: TestClient) -> None:
    payload = {item["scenario_id"]: item for item in client.get("/ui/demo-scenarios").json()}

    injection = payload["prompt-injection-defense"]
    assert injection["run"]["evidence"]["write_outcome"]["status"] == "blocked"
    assert any(message["state"] == "execution prevented" for message in injection["messages"])

    duplicate = payload["duplicate-operation-protection"]
    assert "duplicate" in duplicate["run"]["decision_reason"].lower()
    assert any("Idempotency" in message["evidence_tags"] for message in duplicate["messages"])

    missing = payload["missing-information-clarification"]
    assert missing["run"]["evidence"]["compiler"]["status"] == "clarification_required"
    assert any(message["state"] == "not executable" for message in missing["messages"])


def test_safety_demo_scenarios_never_project_execution(client: TestClient) -> None:
    payload = client.get("/ui/demo-scenarios").json()

    for item in payload[1:]:
        run = item["run"]
        assert run["evidence"]["write_outcome"]["status"] == "blocked"
        assert not run["tools"]
