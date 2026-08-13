"""Privacy-safe diagnostics for structured decision validation failures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DIAGNOSTIC_SCHEMA_VERSION = "structured_output_diagnostic_v1"


class ValidationStage(StrEnum):
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    STRUCTURED_OUTPUT_TRANSPORT_FAILURE = "STRUCTURED_OUTPUT_TRANSPORT_FAILURE"
    FUNCTION_ARGUMENT_DECODE_FAILURE = "FUNCTION_ARGUMENT_DECODE_FAILURE"
    PYDANTIC_CONTRACT_VALIDATION_FAILURE = "PYDANTIC_CONTRACT_VALIDATION_FAILURE"
    POST_VALIDATION_FAILURE = "POST_VALIDATION_FAILURE"


class SanitizedValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    location: str


class StructuredDecisionValidationDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = DIAGNOSTIC_SCHEMA_VERSION
    stage: ValidationStage
    contract_version: str
    error_count: int = Field(ge=0)
    errors: list[SanitizedValidationError] = Field(default_factory=list)
    error_types: list[str] = Field(default_factory=list)
    field_locations: list[str] = Field(default_factory=list)
    validation_layer: str
    provider_success: bool
    structured_call_present: bool | None = None
    tool_call_count: int | None = Field(default=None, ge=0)
    function_name_present: bool | None = None
    arguments_present: bool | None = None
    arguments_decoded: bool | None = None
    typed_model_constructed: bool = False
    argument_payload_kind: str | None = None
    observed_top_level_keys: list[str] = Field(default_factory=list)
    observed_target_keys: list[str] = Field(default_factory=list)
    target_variant: str | None = None
    target_identifier_json_type: str | None = None


class StructuredCallMetadata(TypedDict):
    structured_call_present: bool | None
    tool_call_count: int | None
    function_name_present: bool | None
    arguments_present: bool | None
    arguments_decoded: bool | None
    argument_payload_kind: str | None
    target_variant: str | None
    target_keys: list[str]
    target_identifier_json_type: str | None


def _location(value: object) -> str:
    if isinstance(value, (str, int)):
        return str(value)
    return "<unknown>"


def _field_location(parts: object) -> str:
    if not isinstance(parts, (list, tuple)):
        return "<unknown>"
    return ".".join(_location(part) for part in parts) or "<root>"


def _mapping_keys(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return sorted({str(key) for key in value})


def _shape_metadata(details: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    top_level: set[str] = set()
    target_level: set[str] = set()
    for detail in details:
        value = detail.get("input")
        if not isinstance(value, Mapping):
            continue
        top_level.update(_mapping_keys(value))
        target = value.get("target")
        if isinstance(target, Mapping):
            target_level.update(_mapping_keys(target))
        location = detail.get("loc")
        if isinstance(location, (list, tuple)) and location and location[0] == "target":
            target_level.update(_mapping_keys(value))
    return sorted(top_level), sorted(target_level)


def from_validation_error(
    error: ValidationError,
    *,
    contract_version: str,
    stage: ValidationStage,
    validation_layer: str,
    provider_success: bool,
    structured_call_present: bool | None,
    argument_payload_kind: str | None,
    tool_call_count: int | None = None,
    function_name_present: bool | None = None,
    arguments_present: bool | None = None,
    arguments_decoded: bool | None = None,
    typed_model_constructed: bool = False,
    target_variant: str | None = None,
    target_keys: list[str] | None = None,
    target_identifier_json_type: str | None = None,
) -> StructuredDecisionValidationDiagnostic:
    details = error.errors(include_url=False)
    sanitized = [
        SanitizedValidationError(
            type=str(detail.get("type", "unknown")),
            location=_field_location(detail.get("loc")),
        )
        for detail in details
    ]
    sanitized.sort(key=lambda item: (item.location, item.type))
    top_level, target_level = _shape_metadata(details)
    return StructuredDecisionValidationDiagnostic(
        stage=stage,
        contract_version=contract_version,
        error_count=len(sanitized),
        errors=sanitized,
        error_types=sorted({item.type for item in sanitized}),
        field_locations=sorted({item.location for item in sanitized}),
        validation_layer=validation_layer,
        provider_success=provider_success,
        structured_call_present=structured_call_present,
        tool_call_count=tool_call_count,
        function_name_present=function_name_present,
        arguments_present=arguments_present,
        arguments_decoded=arguments_decoded,
        typed_model_constructed=typed_model_constructed,
        argument_payload_kind=argument_payload_kind,
        observed_top_level_keys=top_level,
        observed_target_keys=target_keys if target_keys is not None else target_level,
        target_variant=target_variant,
        target_identifier_json_type=target_identifier_json_type,
    )


def from_exception(
    error: Exception,
    *,
    contract_version: str,
    stage: ValidationStage,
    validation_layer: str,
    provider_success: bool,
    structured_call_present: bool | None,
    argument_payload_kind: str | None,
    tool_call_count: int | None = None,
    function_name_present: bool | None = None,
    arguments_present: bool | None = None,
    arguments_decoded: bool | None = None,
    typed_model_constructed: bool = False,
    target_variant: str | None = None,
    target_keys: list[str] | None = None,
    target_identifier_json_type: str | None = None,
) -> StructuredDecisionValidationDiagnostic:
    error_type = type(error).__name__
    return StructuredDecisionValidationDiagnostic(
        stage=stage,
        contract_version=contract_version,
        error_count=1,
        errors=[SanitizedValidationError(type=error_type, location="<root>")],
        error_types=[error_type],
        field_locations=["<root>"],
        validation_layer=validation_layer,
        provider_success=provider_success,
        structured_call_present=structured_call_present,
        tool_call_count=tool_call_count,
        function_name_present=function_name_present,
        arguments_present=arguments_present,
        arguments_decoded=arguments_decoded,
        typed_model_constructed=typed_model_constructed,
        argument_payload_kind=argument_payload_kind,
        observed_target_keys=target_keys or [],
        target_variant=target_variant,
        target_identifier_json_type=target_identifier_json_type,
    )


def structured_call_metadata(response: object) -> StructuredCallMetadata:
    """Return bounded structure metadata without retaining response content."""

    tool_calls = getattr(response, "tool_calls", None)
    if not isinstance(tool_calls, list):
        tool_calls = []
    tool_call_count = len(tool_calls)
    function_name_present = False
    arguments_present = False
    arguments_decoded = False
    target_variant: str | None = None
    target_keys: list[str] = []
    target_identifier_json_type: str | None = None

    def json_type(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return type(value).__name__

    for tool_call in tool_calls:
        if not isinstance(tool_call, Mapping):
            continue
        function = tool_call.get("function")
        if isinstance(function, Mapping):
            function_name_present = function_name_present or isinstance(function.get("name"), str)
            arguments = function.get("arguments")
        else:
            function_name_present = function_name_present or isinstance(tool_call.get("name"), str)
            arguments = tool_call.get("args")
        if arguments is not None:
            arguments_present = True
        if isinstance(arguments, Mapping):
            arguments_decoded = True
            target = arguments.get("target")
            if isinstance(target, Mapping):
                candidate_variant = target.get("type")
                if candidate_variant in {"explicit_order", "latest_order", "explicit_ticket"}:
                    target_variant = str(candidate_variant)
                target_keys = _mapping_keys(target)
                identifier_key = (
                    "order_id"
                    if "order_id" in target
                    else "ticket_id"
                    if "ticket_id" in target
                    else None
                )
                if identifier_key is not None:
                    target_identifier_json_type = json_type(target.get(identifier_key))
    invalid_tool_calls = getattr(response, "invalid_tool_calls", None)
    if isinstance(invalid_tool_calls, list) and invalid_tool_calls:
        arguments_present = True
        arguments_decoded = False
    return {
        "structured_call_present": tool_call_count > 0,
        "tool_call_count": tool_call_count,
        "function_name_present": function_name_present,
        "arguments_present": arguments_present,
        "arguments_decoded": arguments_decoded,
        "argument_payload_kind": "mapping"
        if arguments_decoded
        else ("present" if arguments_present else None),
        "target_variant": target_variant,
        "target_keys": target_keys,
        "target_identifier_json_type": target_identifier_json_type,
    }


def canonical_schema_hash(schema: Mapping[str, Any]) -> str:
    payload = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def transport_parameters(runnable: object) -> dict[str, Any] | None:
    for step in getattr(runnable, "steps", ()):
        kwargs = getattr(step, "kwargs", {})
        tools = kwargs.get("tools") if isinstance(kwargs, Mapping) else None
        if not isinstance(tools, list) or not tools:
            continue
        function = tools[0].get("function") if isinstance(tools[0], Mapping) else None
        parameters = function.get("parameters") if isinstance(function, Mapping) else None
        if isinstance(parameters, dict):
            return parameters
    return None
