from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.llm.fake import FakeSemanticDecisionV3Provider
from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.runtime import AgentRuntime
from app.agent.schemas import (
    ExplicitOrderTargetV3,
    ExplicitTicketTargetV3,
    Intent,
    LatestOrderTargetV3,
    SemanticDecision,
    SemanticDecisionV3,
    normalize_semantic_decision,
)
from app.agent.semantic_grounding import GroundingStatus, validate_semantic_grounding
from app.core.config import Settings
from app.models import Order
from evaluation.fixtures import evaluation_session
from evaluation.live_cases import (
    LIVE_CASE_SET_V1_1_VERSION,
    LIVE_CASE_SET_VERSION,
    LIVE_EVAL_V1_1_FAKE_ORDER_ID,
    live_cases,
    live_cases_v1_1,
)
from evaluation.live_scoring import case_set_metadata
from evaluation.provenance import (
    build_provenance,
    prompt_hash_for_contract,
    schema_hash_for_contract,
    validate_provenance,
)


def _transport_branches() -> dict[str, dict[str, Any]]:
    provider = OpenAICompatibleProvider(
        Settings(
            _env_file=None,
            agent_decision_contract_version="semantic_decision_v3",
            llm_structured_output_mode="function_calling",
        )
    )
    assert provider._transport_schema is not None
    target = provider._transport_schema["properties"]["target"]
    union = next(item for item in target["anyOf"] if "oneOf" in item)
    return {branch["properties"]["type"]["const"]: branch for branch in union["oneOf"]}


def test_v3_target_union_is_complete_strict_and_discriminated() -> None:
    complete_order = SemanticDecisionV3(
        intent=Intent.ORDER_CANCEL,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=7),
    )
    assert normalize_semantic_decision(complete_order) == SemanticDecision(
        intent=Intent.ORDER_CANCEL,
        target={"type": "explicit_order", "order_id": 7},
    )
    assert (
        SemanticDecisionV3(
            intent=Intent.ORDER_LOOKUP,
            target=LatestOrderTargetV3(type="latest_order"),
        ).target
        is not None
    )
    assert (
        SemanticDecisionV3(
            intent=Intent.TICKET_LOOKUP,
            target=ExplicitTicketTargetV3(type="explicit_ticket", ticket_id=4),
        ).target
        is not None
    )

    with pytest.raises(ValidationError):
        SemanticDecisionV3.model_validate(
            {"intent": "order_cancel", "target": {"type": "explicit_order"}}
        )
    with pytest.raises(ValidationError):
        SemanticDecisionV3.model_validate(
            {"intent": "ticket_lookup", "target": {"type": "explicit_ticket"}}
        )
    with pytest.raises(ValidationError):
        SemanticDecisionV3.model_validate(
            {
                "intent": "order_lookup",
                "target": {"type": "latest_order", "order_id": 7},
            }
        )

    target_schema = SemanticDecisionV3.model_json_schema()["properties"]["target"]
    discriminated = next(item for item in target_schema["anyOf"] if "oneOf" in item)
    assert discriminated["discriminator"]["propertyName"] == "type"


def test_v3_transport_schema_exposes_branch_local_required_identifiers() -> None:
    branches = _transport_branches()
    assert set(branches) == {"explicit_order", "latest_order", "explicit_ticket"}
    assert branches["explicit_order"]["required"] == ["type", "order_id"]
    assert branches["explicit_ticket"]["required"] == ["type", "ticket_id"]
    assert branches["latest_order"]["required"] == ["type"]
    assert set(branches["latest_order"]["properties"]) == {"type"}
    assert all(branch["additionalProperties"] is False for branch in branches.values())


def test_v2_and_v3_share_the_hardened_prompt_and_have_distinct_schemas() -> None:
    assert schema_hash_for_contract("semantic_decision_v2") == (
        "3e3a4e21a215c612a9449532cb421d2d97b42d172ad1513843fd40c659a29bc7"
    )
    assert prompt_hash_for_contract("semantic_decision_v2") == (
        "d2cf899be3b826285e8e8f8d2c3f7d1332d6b4f5ed2d0b90fbec5e4ab11cf365"
    )
    assert schema_hash_for_contract("semantic_decision_v3") != schema_hash_for_contract(
        "semantic_decision_v2"
    )
    assert prompt_hash_for_contract("semantic_decision_v3") == prompt_hash_for_contract(
        "semantic_decision_v2"
    )
    assert Settings(_env_file=None).agent_decision_contract_version == "direct_tool_v1"
    assert (
        Settings(
            _env_file=None, agent_decision_contract_version="semantic_decision_v3"
        ).agent_decision_contract_version
        == "semantic_decision_v3"
    )


def test_live_eval_v1_1_is_a_narrow_two_case_identifier_patch() -> None:
    historical = live_cases()
    aligned = live_cases_v1_1()
    assert len(historical) == len(aligned) == 28
    assert sum(case.language == "en" for case in aligned) == 14
    assert sum(case.language == "tr" for case in aligned) == 14
    assert [case.id for case in historical] == [case.id for case in aligned]
    assert Counter(case.category for case in historical) == Counter(
        case.category for case in aligned
    )

    changed: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for old, new in zip(historical, aligned, strict=True):
        if old != new:
            old_payload = old.model_dump(mode="json")
            new_payload = new.model_dump(mode="json")
            changed[old.id] = (old_payload, new_payload)
            differing_fields = {key for key in old_payload if old_payload[key] != new_payload[key]}
            assert differing_fields == {"input"}
    assert set(changed) == {"en-fake-id", "tr-fake-id"}
    assert all(str(LIVE_EVAL_V1_1_FAKE_ORDER_ID) in new["input"] for _, new in changed.values())

    old_metadata = case_set_metadata(historical, version=LIVE_CASE_SET_VERSION)
    new_metadata = case_set_metadata(aligned, version=LIVE_CASE_SET_V1_1_VERSION)
    assert old_metadata["sha256"] == (
        "888e8ed77435d8eb864ae01784852798c17e0f1829400296ba78305b3b95d6ae"
    )
    assert new_metadata["sha256"] != old_metadata["sha256"]


def test_live_eval_v1_1_fake_order_id_is_absent_from_evaluation_fixtures() -> None:
    session = evaluation_session()
    try:
        assert (
            session.scalar(select(Order.id).where(Order.id == LIVE_EVAL_V1_1_FAKE_ORDER_ID)) is None
        )
    finally:
        session.close()


def test_v1_1_fake_integer_is_grounded_without_becoming_business_valid() -> None:
    case = next(case for case in live_cases_v1_1() if case.id == "en-fake-id")
    proposal = SemanticDecisionV3(
        intent=Intent.ORDER_CANCEL,
        target=ExplicitOrderTargetV3(type="explicit_order", order_id=LIVE_EVAL_V1_1_FAKE_ORDER_ID),
    )
    grounding = validate_semantic_grounding(
        normalize_semantic_decision(proposal), case.rendered_input()
    )
    assert grounding.status == GroundingStatus.GROUNDED


def test_v3_provenance_binds_v1_1_and_actual_contract_identity() -> None:
    cases = live_cases_v1_1()
    metadata = case_set_metadata(cases, version=LIVE_CASE_SET_V1_1_VERSION)

    class Args:
        model = "diagnostic-model"
        base_url = "http://localhost:11434/v1"
        structured_output_mode = "function_calling"
        reasoning_effort = "none"
        temperature = 0.0
        timeout = 30.0

    provenance = build_provenance(
        args=Args(),
        case_set_version=LIVE_CASE_SET_V1_1_VERSION,
        case_set_hash=str(metadata["sha256"]),
        prompt_hash=prompt_hash_for_contract("semantic_decision_v3"),
        scoring_version="structured_output_diagnostic_v1",
        runs_per_case=3,
        unique_cases=28,
        total_attempts=84,
        decision_contract_version="semantic_decision_v3",
    )
    validate_provenance(provenance)
    assert provenance["decision_contract"] == {
        "version": "semantic_decision_v3",
        "schema_hash": schema_hash_for_contract("semantic_decision_v3"),
    }
    assert provenance["benchmark"]["case_set_version"] == LIVE_CASE_SET_V1_1_VERSION


def test_v3_uses_existing_grounding_compiler_policy_and_stored_action(
    db_session: Any,
) -> None:
    provider = FakeSemanticDecisionV3Provider(
        [
            SemanticDecisionV3(
                intent=Intent.ORDER_CANCEL,
                target=ExplicitOrderTargetV3(type="explicit_order", order_id=3),
            )
        ]
    )
    runtime = AgentRuntime(provider=provider, decision_contract_version="semantic_decision_v3")
    first = runtime.run(
        conversation_id="semantic-v3-confirmation",
        customer_id=1,
        message="Cancel order 3.",
        session=db_session,
    )
    assert first.pending_action is not None
    action_id = first.pending_action.action_id
    confirmed = runtime.run(
        conversation_id="semantic-v3-confirmation",
        customer_id=1,
        message="confirm",
        session=db_session,
    )
    replay = runtime.run(
        conversation_id="semantic-v3-confirmation",
        customer_id=1,
        message="confirm",
        session=db_session,
    )
    assert confirmed.pending_action is not None
    assert replay.pending_action is not None
    assert confirmed.pending_action.action_id == replay.pending_action.action_id == action_id
    assert len(provider.calls) == 1
