from __future__ import annotations

import pytest

from evaluation.structured_output_diagnostics import DIAGNOSTIC_CASE_IDS, RUNS_PER_CASE
from evaluation.structured_output_openai_control import (
    MAX_GENERATION_CALLS,
    MEASURED_ATTEMPTS,
    GenerationCallBudget,
    control_configuration,
    select_luna_model,
)


def test_luna_selector_requires_exact_available_luna_and_never_falls_back() -> None:
    assert select_luna_model(["gpt-5.5", "gpt-5.6-luna", "gpt-5.6-terra"]) == "gpt-5.6-luna"
    with pytest.raises(RuntimeError, match="OPENAI_LUNA_NOT_AVAILABLE"):
        select_luna_model(["gpt-5.6-terra", "gpt-5.6-sol"])


def test_generation_budget_is_one_warmup_plus_24_measured_calls() -> None:
    budget = GenerationCallBudget()
    for _ in range(MAX_GENERATION_CALLS):
        budget.consume()
    assert budget.calls == 25
    with pytest.raises(RuntimeError, match="generation call budget exceeded"):
        budget.consume()
    assert MEASURED_ATTEMPTS == 24
    assert len(DIAGNOSTIC_CASE_IDS) == 8
    assert RUNS_PER_CASE == 3


def test_openai_control_configuration_matches_local_methodology() -> None:
    config = control_configuration("gpt-5.6-luna")
    assert config["provider"] == "openai"
    assert config["runtime"] == "OpenAI API"
    assert config["decision_contract_version"] == "semantic_decision_v2"
    assert config["schema_hash"] == (
        "6e24a900ec1610a0d90d4fa720c61d29ecb50b85b1be9882eb000f9d1d8ec5e3"
    )
    assert config["prompt_hash"] == (
        "d2cf899be3b826285e8e8f8d2c3f7d1332d6b4f5ed2d0b90fbec5e4ab11cf365"
    )
    assert config["structured_output_mode"] == "function_calling"
    assert config["reasoning_effort"] == "none"
    assert config["temperature"] == 0.0
    assert config["timeout_seconds"] == 30.0
    assert config["retry_policy"] == {
        "sdk_max_retries": 0,
        "application_retry_attempts": 0,
    }
