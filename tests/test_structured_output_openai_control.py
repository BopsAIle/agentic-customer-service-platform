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
        "3e3a4e21a215c612a9449532cb421d2d97b42d172ad1513843fd40c659a29bc7"
    )
    assert config["prompt_hash"] == (
        "4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0"
    )
    assert config["structured_output_mode"] == "function_calling"
    assert config["reasoning_effort"] == "none"
    assert config["temperature"] == 0.0
    assert config["timeout_seconds"] == 30.0
    assert config["retry_policy"] == {
        "sdk_max_retries": 0,
        "application_retry_attempts": 0,
    }
