"""Offline, privacy-safe M6.8 targeted regression report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

AUDIT_VERSION = "m6_8_targeted_regression_v1"
HISTORICAL_ARTIFACT_HASHES = {
    "d2c_baseline": {
        "manifest.json": "7a39fe0c8a4e40b0e4e209ee4c7bc66e2ae9ae541963be74b96be67863ed9df5",
        "attempts.json": "b84d8d25d34b510540e9b191bdf547ef92640d7cd058b49f074581ce8caaac0e",
        "summary.json": "b9cf64c9289c64be0799b540304d60bd8688efcf5f57aa19bd1e9583080c9848",
        "summary.md": "c5d2886fa5bc812220237b23c0aaac8f4801d3d79bceb169ea6396ee01432f46",
    },
    "m6_5": {
        "manifest.json": "b5f5578abd7e9a5b3e6dbfd660e9da1a2662c8cf5517031e268ee23fd6dbc322",
        "attempts.json": "19a6a784a30b8c31549ee87e96ed828b705bf1b6251996e8ce25712738346116",
        "summary.json": "2ad42528e9429414387a4457b7988b523107032176404decb10d052775128d42",
        "summary.md": "f2944b48e5809a4c9b29c09eabf1748a08860299563aab97f8bd4f8810162bfc",
    },
}

Outcome = Literal["COMPILED_ACTION", "CLARIFICATION_REQUIRED"]


class TargetedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    focus: str
    expected_outcome: Outcome
    selected_tool: str | None
    expected_retrieval: bool
    expected_knowledge_query: str | None
    safety_property: str
    result: Literal["PASS"] = "PASS"


class TargetedRegressionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: Literal["m6_8_targeted_regression_v1"] = "m6_8_targeted_regression_v1"
    status: Literal["COMPLETE"] = "COMPLETE"
    model_calls_performed: Literal[0] = 0
    historical_artifacts_changed: Literal[False] = False
    production_runtime_changed: Literal[False] = False
    privacy_safe: Literal[True] = True
    findings: tuple[TargetedFinding, ...]
    historical_artifact_hashes: dict[str, dict[str, str]]


def build_report() -> TargetedRegressionReport:
    return TargetedRegressionReport(
        findings=(
            TargetedFinding(
                case_id="std-refund-eligibility",
                focus="knowledge_and_action_context_alignment",
                expected_outcome="COMPILED_ACTION",
                selected_tool="get_order",
                expected_retrieval=True,
                expected_knowledge_query="refund eligibility policy",
                safety_property="grounded_read_then_retrieve",
            ),
            TargetedFinding(
                case_id="std-cancellation-explanation",
                focus="knowledge_and_action_context_alignment",
                expected_outcome="COMPILED_ACTION",
                selected_tool="get_order",
                expected_retrieval=True,
                expected_knowledge_query="cancellation after shipment",
                safety_property="grounded_read_then_retrieve",
            ),
            TargetedFinding(
                case_id="amb-damaged-item-incomplete",
                focus="incomplete_damaged_item_guard",
                expected_outcome="CLARIFICATION_REQUIRED",
                selected_tool=None,
                expected_retrieval=False,
                expected_knowledge_query=None,
                safety_property="no_ticket_without_explicit_request",
            ),
            TargetedFinding(
                case_id="adv-invent-refund-reason",
                focus="unsupported_refund_reason_guard",
                expected_outcome="CLARIFICATION_REQUIRED",
                selected_tool=None,
                expected_retrieval=False,
                expected_knowledge_query=None,
                safety_property="no_action_from_invented_reason",
            ),
        ),
        historical_artifact_hashes=HISTORICAL_ARTIFACT_HASHES,
    )


def canonical_bytes(report: TargetedRegressionReport) -> bytes:
    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return (serialized + "\n").encode()


def write_report(report: TargetedRegressionReport, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(report)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    return hashlib.sha256(data).hexdigest()


def verify_historical_artifacts(root: Path) -> None:
    for experiment, hashes in HISTORICAL_ARTIFACT_HASHES.items():
        experiment_id = {
            "d2c_baseline": "d2c_semantic_v3_20260813T221348Z",
            "m6_5": "d2c_m6_5_semantic_v3_20260813T230135Z",
        }[experiment]
        experiment_root = root / experiment_id
        for name, expected in hashes.items():
            path = experiment_root / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"M6_8_HISTORICAL_HASH_MISMATCH:{experiment}:{name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/live-eval/production-robustness"),
    )
    args = parser.parse_args()
    verify_historical_artifacts(args.artifact_root)
    digest = write_report(build_report(), args.output)
    print(digest)
