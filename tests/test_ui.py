import json

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeDecisionProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentRequestType, Intent, StructuredDecision
from app.memory.models import MemoryRecord
from app.memory.schemas import MemorySource, MemoryStatus, MemoryType
from app.ui.projection import get_projection_store


def _decision() -> StructuredDecision:
    return StructuredDecision(
        intent=Intent.ORDER_LIST,
        request_type=AgentRequestType.READ_ACTION,
        tool_name="get_customer_orders",
        arguments={"customer_id": 1},
        reason="operator UI test",
    )


def test_ui_projection_exposes_bounded_run_metadata_without_message_or_result_values(
    db_session: Session, client: TestClient
) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision()]),
        checkpointer=MemorySaver(),
    )
    response = runtime.run(
        conversation_id="ui-conversation-1",
        customer_id=1,
        message="Show my orders and include all private details.",
        session=db_session,
    )

    run = get_projection_store().get_run(response.agent_run_id)
    assert run is not None
    assert run.customer_id == 1
    assert run.path
    assert run.tools[0].name == "get_customer_orders"
    assert run.tools[0].result_fields

    payload = client.get(f"/ui/agent-runs/{response.agent_run_id}").json()
    assert payload["run_id"] == response.agent_run_id
    assert "Show my orders" not in str(payload)
    assert "Test Customer" not in str(payload)
    assert "test@example.com" not in str(payload)
    assert "25.00" not in str(payload)


def test_ui_memory_endpoint_is_customer_scoped_and_returns_safe_fields(
    db_session: Session, client: TestClient
) -> None:
    private_content = "PRIVATE_MEMORY_SENTINEL_DO_NOT_EXPOSE"
    db_session.add(
        MemoryRecord(
            customer_id=1,
            memory_type=MemoryType.PREFERENCE,
            content=private_content,
            normalized_key="response_style",
            source=MemorySource.USER_EXPLICIT,
            confidence=1.0,
            status=MemoryStatus.ACTIVE,
        )
    )
    db_session.commit()
    customer_one = client.get("/ui/memory/1")
    customer_two = client.get("/ui/memory/2")

    assert customer_one.status_code == 200
    payload = customer_one.json()
    assert set(payload[0]) == {
        "id",
        "customer_id",
        "memory_type",
        "normalized_key",
        "source",
        "status",
        "created_at",
        "updated_at",
        "expires_at",
    }
    assert payload[0]["customer_id"] == 1
    assert payload[0]["memory_type"] == "preference"
    assert payload[0]["normalized_key"] == "response_style"
    assert payload[0]["source"] == "user_explicit"
    assert "content" not in payload[0]
    assert private_content not in json.dumps(payload, sort_keys=True)
    assert private_content not in customer_one.text
    assert customer_two.status_code == 200
    assert customer_two.json() == []


def test_ui_read_endpoints_and_health_have_bounded_contract(
    db_session: Session, client: TestClient
) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision()]),
        checkpointer=MemorySaver(),
    )
    response = runtime.run(
        conversation_id="ui-conversation-2",
        customer_id=1,
        message="List my orders.",
        session=db_session,
    )
    assert client.get(f"/ui/tool-events/{response.agent_run_id}").status_code == 200
    assert client.get(f"/ui/policy-events/{response.agent_run_id}").status_code == 200
    assert client.get(f"/ui/rag-events/{response.agent_run_id}").status_code == 200
    assert client.get(f"/ui/traces/{response.agent_run_id}").status_code == 200
    health = client.get("/ui/system-health")
    missing = client.get("/ui/agent-runs/not-a-real-run")

    assert health.status_code == 200
    assert {component["name"] for component in health.json()["components"]} >= {
        "database",
        "memory",
    }
    assert missing.status_code == 404


def test_ui_conversation_projection_does_not_return_raw_messages(
    db_session: Session, client: TestClient
) -> None:
    runtime = AgentRuntime(
        provider=FakeDecisionProvider([_decision()]),
        checkpointer=MemorySaver(),
    )
    runtime.run(
        conversation_id="ui-conversation-3",
        customer_id=1,
        message="A private operator message.",
        session=db_session,
    )
    payload = client.get("/ui/conversations/ui-conversation-3").json()

    assert payload["run_count"] == 1
    assert payload["messages"][0]["content_available"] is False
    assert "content" not in payload["messages"][0]
    assert "A private operator message" not in str(payload)
