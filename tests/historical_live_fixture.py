"""Tracked deterministic fallback for tests that exercise historical rescore paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from evaluation.live_cases import live_cases
from evaluation.live_scoring import LiveAttempt, summarize
from evaluation.live_scoring_v3 import CASE_SET_SHA256, CASE_SET_VERSION, PROMPT_HASH


def _attempts() -> list[LiveAttempt]:
    attempts: list[LiveAttempt] = []
    for case in live_cases():
        for run_number in range(1, 4):
            tool = case.expected_tools[0] if case.expected_tools else None
            arguments = dict(case.expected_arguments)
            if tool == "create_support_ticket":
                arguments.update({"category": "delivery", "description": "fixture"})
            elif tool == "request_refund":
                arguments["reason"] = "fixture"
            elif tool == "escalate_to_human":
                arguments.update({"priority": "urgent", "reason": "fixture", "summary": "fixture"})
            attempts.append(
                LiveAttempt(
                    case_id=case.id,
                    language=case.language,
                    category=case.category,
                    run_number=run_number,
                    schema_valid=True,
                    actual_intent=case.expected_intents[0].value
                    if case.expected_intents
                    else "unknown",
                    expected_intents=[intent.value for intent in case.expected_intents],
                    actual_tool=tool,
                    expected_tools=list(case.expected_tools),
                    argument_structural_valid=True if tool else None,
                    argument_semantic_correct=True if tool else None,
                    clarification_correct=case.expect_clarification
                    if case.expect_clarification
                    else None,
                    latency_ms=1.0,
                    actual_arguments=arguments,
                )
            )
    return attempts


def historical_artifact(model: str) -> dict[str, Any]:
    attempts = _attempts()
    metadata: dict[str, Any] = {
        "model": model,
        "provider": "openai_compatible",
        "base_url_classification": "local",
        "structured_output_mode": "schema",
        "reasoning_effort": "none",
        "temperature": 0.0,
        "timeout_seconds": 30.0,
        "case_set_version": CASE_SET_VERSION,
        "case_set_sha256": CASE_SET_SHA256,
        "prompt_hash": PROMPT_HASH,
        "scoring_version": "live_scoring_v2",
        "source_revision": "deterministic-test-fixture",
        "runs_per_case": 3,
        "case_count": 28,
        "attempts": 84,
        "decision_contract_version": "direct_tool_v1",
    }
    return {
        "schema_version": "1.0",
        "metadata": metadata,
        "summary": summarize(attempts).model_dump(mode="json"),
        "per_language": {
            language: summarize(
                [item for item in attempts if item.language == language]
            ).model_dump(mode="json")
            for language in ("en", "tr")
        },
        "per_category": {
            category: summarize(
                [item for item in attempts if item.category == category]
            ).model_dump(mode="json")
            for category in sorted({item.category for item in attempts})
        },
        "attempts": [item.model_dump(mode="json") for item in attempts],
        "top_failure_modes": [],
    }


def load_artifact(path: Path, model: str) -> dict[str, Any]:
    if path.exists():
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    return historical_artifact(model)


def write_artifact(path: Path, model: str) -> None:
    path.write_text(
        json.dumps(historical_artifact(model), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
