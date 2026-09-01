from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.agent.llm.diagnostics import (
    DIAGNOSTIC_SCHEMA_VERSION,
    ValidationStage,
    from_exception,
    from_validation_error,
    structured_call_metadata,
)
from app.agent.llm.provider import OpenAICompatibleProvider
from app.agent.schemas import SemanticDecision
from app.core.config import Settings


def _invalid_payload() -> dict[str, Any]:
    return {
        "request_type": "write_action",
        "target": {"type": "explicit_order", "order_id": {"value": "sk-secret"}},
        "tool_name": "cancel_order",
        "customer_id": 42,
        "reason": "private reason text",
    }


def test_validation_diagnostic_is_sanitized_and_deterministic() -> None:
    with pytest.raises(ValidationError) as raised:
        SemanticDecision.model_validate(_invalid_payload())
    diagnostic = from_validation_error(
        raised.value,
        contract_version="semantic_decision_v2",
        stage=ValidationStage.PYDANTIC_CONTRACT_VALIDATION_FAILURE,
        validation_layer="pydantic_contract",
        provider_success=True,
        structured_call_present=True,
        argument_payload_kind="dict",
    )
    encoded = diagnostic.model_dump_json()
    assert diagnostic.schema_version == DIAGNOSTIC_SCHEMA_VERSION
    assert "sk-secret" not in encoded
    assert "ord-123" not in encoded
    assert "private reason text" not in encoded
    assert "42" not in encoded
    assert "tool_name" in diagnostic.observed_top_level_keys
    assert diagnostic.errors == sorted(
        diagnostic.errors, key=lambda item: (item.location, item.type)
    )


def test_missing_extra_and_nested_errors_are_preserved_without_values() -> None:
    with pytest.raises(ValidationError) as raised:
        SemanticDecision.model_validate(
            {"target": {"type": "explicit_order", "order_id": []}, "unknown": "x"}
        )
    diagnostic = from_validation_error(
        raised.value,
        contract_version="semantic_decision_v2",
        stage=ValidationStage.PYDANTIC_CONTRACT_VALIDATION_FAILURE,
        validation_layer="pydantic_contract",
        provider_success=True,
        structured_call_present=True,
        argument_payload_kind="dict",
    )
    assert diagnostic.error_count >= 2
    assert diagnostic.field_locations
    encoded = diagnostic.model_dump_json()
    assert '"x"' not in encoded


class _Response:
    def __init__(self, tool_calls: object, invalid_tool_calls: object = None) -> None:
        self.tool_calls = tool_calls
        self.invalid_tool_calls = invalid_tool_calls


def test_no_tool_call_metadata_is_explicit_and_value_free() -> None:
    metadata = structured_call_metadata(_Response([]))
    assert metadata == {
        "structured_call_present": False,
        "tool_call_count": 0,
        "function_name_present": False,
        "arguments_present": False,
        "arguments_decoded": False,
        "argument_payload_kind": None,
        "target_variant": None,
        "target_keys": [],
        "target_identifier_json_type": None,
    }


def test_tool_call_without_arguments_is_not_decoded() -> None:
    metadata = structured_call_metadata(_Response([{"name": "SemanticDecision"}]))
    assert metadata["structured_call_present"] is True
    assert metadata["tool_call_count"] == 1
    assert metadata["function_name_present"] is True
    assert metadata["arguments_present"] is False
    assert metadata["arguments_decoded"] is False


def test_tool_call_with_malformed_arguments_is_present_but_not_decoded() -> None:
    metadata = structured_call_metadata(
        _Response([{"name": "SemanticDecision", "args": "private-order-123"}])
    )
    assert metadata["arguments_present"] is True
    assert metadata["arguments_decoded"] is False
    assert "private-order-123" not in str(metadata)


def test_decoded_arguments_metadata_is_structural_only() -> None:
    metadata = structured_call_metadata(
        _Response(
            [
                {
                    "name": "SemanticDecision",
                    "args": {"intent": "order_cancel", "reason": "private"},
                }
            ]
        )
    )
    assert metadata["arguments_present"] is True
    assert metadata["arguments_decoded"] is True
    assert "private" not in str(metadata)


def test_target_metadata_is_bounded_to_schema_shape_and_json_type() -> None:
    metadata = structured_call_metadata(
        _Response(
            [
                {
                    "name": "SemanticDecision",
                    "args": {
                        "target": {
                            "type": "explicit_order",
                            "order_id": "private-order-123",
                        }
                    },
                }
            ]
        )
    )
    assert metadata["target_variant"] == "explicit_order"
    assert metadata["target_keys"] == ["order_id", "type"]
    assert metadata["target_identifier_json_type"] == "string"
    assert "private-order-123" not in str(metadata)


def test_structural_stage_diagnostics_distinguish_call_states() -> None:
    no_call = from_exception(
        TypeError("no tool call"),
        contract_version="semantic_decision_v2",
        stage=ValidationStage.STRUCTURED_OUTPUT_TRANSPORT_FAILURE,
        validation_layer="structured_output_transport",
        provider_success=True,
        structured_call_present=False,
        tool_call_count=0,
        function_name_present=False,
        arguments_present=False,
        arguments_decoded=False,
        argument_payload_kind=None,
    )
    no_args = from_exception(
        TypeError("missing arguments"),
        contract_version="semantic_decision_v2",
        stage=ValidationStage.FUNCTION_ARGUMENT_DECODE_FAILURE,
        validation_layer="structured_output_parser",
        provider_success=True,
        structured_call_present=True,
        tool_call_count=1,
        function_name_present=True,
        arguments_present=False,
        arguments_decoded=False,
        argument_payload_kind=None,
    )
    assert no_call.tool_call_count == 0
    assert no_call.function_name_present is False
    assert no_args.structured_call_present is True
    assert no_args.arguments_present is False
    assert no_args.arguments_decoded is False


def test_transport_schema_metadata_matches_contract_without_prompt_or_values() -> None:
    settings = Settings(
        _env_file=None,
        llm_model="qwen3.5:4b",
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="ollama",
        llm_temperature=0.0,
        llm_reasoning_effort="none",
        llm_structured_output_mode="function_calling",
        agent_decision_contract_version="semantic_decision_v2",
    )
    provider = OpenAICompatibleProvider(settings)
    metadata = provider.structured_schema_metadata()
    assert metadata["transport_schema_available"] is True
    assert metadata["contract_schema_hash"] == (
        "6e24a900ec1610a0d90d4fa720c61d29ecb50b85b1be9882eb000f9d1d8ec5e3"
    )
    assert metadata["transport_top_level_keys"] == metadata["contract_top_level_keys"]
    assert metadata["transport_required_keys"] == metadata["contract_required_keys"]
    assert "system_semantic_decision_v2" not in str(metadata)


def test_provider_request_contract_settings_remain_unchanged() -> None:
    settings = Settings(
        _env_file=None,
        llm_model="qwen3.5:4b",
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="ollama",
        llm_temperature=0.0,
        llm_reasoning_effort="none",
        llm_structured_output_mode="function_calling",
        agent_decision_contract_version="semantic_decision_v2",
        llm_timeout_seconds=30.0,
        llm_connect_timeout_seconds=5.0,
    )
    provider = OpenAICompatibleProvider(settings)
    binding = cast(Any, provider._model).steps[0]
    assert binding.kwargs["ls_structured_output_format"]["kwargs"]["method"] == ("function_calling")
    assert binding.bound.temperature == 0.0
    assert binding.bound.reasoning_effort == "none"
    assert binding.bound.max_retries == 0
    assert binding.bound.request_timeout.read == 30.0
