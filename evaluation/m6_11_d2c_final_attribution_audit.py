"""Offline attribution audit for the immutable M6.10 D2c rerun."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from evaluation.d2c_audit import (
    classify_compiler_failure,
    classify_resolver_failure,
    classify_routing_failure,
)
from evaluation.d2c_runner import D2cAttemptArtifact
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases
from evaluation.provenance import hash_prompt_bytes

AUDIT_VERSION = "m6_11_d2c_final_attribution_audit_v1"
SOURCE_EXPERIMENT_ID = "d2c_m6_9_semantic_v3_20260813T233308Z"
SOURCE_REVISION = "518fa11519a69e5bfcda12bf1f7b1492eac3f2f9"
SOURCE_ROOT = Path("artifacts/live-eval/production-robustness") / SOURCE_EXPERIMENT_ID
SOURCE_HASHES = {
    "manifest.json": "ea68ef30f3d6c5e4caf425aba1e928748573e130baff39e171c5f41e58cdb187",
    "attempts.json": "700e8f9a616d01a649da19cd6e12928d21320e500c5356bb18bc82c61a849233",
    "summary.json": "251174a84e34cc4dd93971676cba41986212a471a3bec230021a4052b41aca23",
    "summary.md": "7c77dfd5ab5c50e521a9b08d7f877c2b9e958ef82a9d208f5a981ac3477fa911",
}

HISTORICAL_HASHES = {
    "d2c_semantic_v3_20260813T221348Z": {
        "manifest.json": "7a39fe0c8a4e40b0e4e209ee4c7bc66e2ae9ae541963be74b96be67863ed9df5",
        "attempts.json": "b84d8d25d34b510540e9b191bdf547ef92640d7cd058b49f074581ce8caaac0e",
        "summary.json": "b9cf64c9289c64be0799b540304d60bd8688efcf5f57aa19bd1e9583080c9848",
        "summary.md": "c5d2886fa5bc812220237b23c0aaac8f4801d3d79bceb169ea6396ee01432f46",
    },
    "d2c_m6_5_semantic_v3_20260813T230135Z": {
        "manifest.json": "b5f5578abd7e9a5b3e6dbfd660e9da1a2662c8cf5517031e268ee23fd6dbc322",
        "attempts.json": "19a6a784a30b8c31549ee87e96ed828b705bf1b6251996e8ce25712738346116",
        "summary.json": "2ad42528e9429414387a4457b7988b523107032176404decb10d052775128d42",
        "summary.md": "f2944b48e5809a4c9b29c09eabf1748a08860299563aab97f8bd4f8810162bfc",
    },
}

RoutingAttribution = Literal[
    "oracle_path_mismatch",
    "valid_semantic_equivalent",
    "wrong_intent",
    "wrong_tool_route_mapping",
    "genuine_model_semantic_failure",
]
ResolverAttribution = Literal[
    "invalid_expectation",
    "upstream_clarification",
    "resolver_ineligible",
    "genuine_resolver_failure",
]
UnsafeAttribution = Literal[
    "valid_policy_rejection",
    "false_positive",
    "genuine_unsafe_semantic_decision",
]


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    pair_id: str
    language: Literal["en", "tr"]
    category: str
    repetition: int
    attribution: str
    evidence_codes: tuple[str, ...]


class FinalAttributionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: Literal["m6_11_d2c_final_attribution_audit_v1"] = (
        "m6_11_d2c_final_attribution_audit_v1"
    )
    status: Literal["COMPLETE"] = "COMPLETE"
    source_experiment_id: Literal["d2c_m6_9_semantic_v3_20260813T233308Z"] = (
        "d2c_m6_9_semantic_v3_20260813T233308Z"
    )
    source_revision: Literal["518fa11519a69e5bfcda12bf1f7b1492eac3f2f9"] = (
        "518fa11519a69e5bfcda12bf1f7b1492eac3f2f9"
    )
    source_artifact_sha256: dict[str, str]
    model_calls_performed: Literal[0] = 0
    model_outputs_changed: Literal[False] = False
    historical_artifacts_changed: Literal[False] = False
    routing_mismatches: int
    resolver_failures: int
    unsafe_proposals: int
    routing_attribution_counts: dict[str, int]
    resolver_attribution_counts: dict[str, int]
    unsafe_attribution_counts: dict[str, int]
    routing_records: tuple[AuditRecord, ...]
    resolver_records: tuple[AuditRecord, ...]
    unsafe_records: tuple[AuditRecord, ...]
    conclusions: tuple[str, ...]
    privacy: dict[str, bool]


def _sha256(path: Path) -> str:
    return hash_prompt_bytes(path.read_bytes())


def validate_source_artifacts(source_root: Path = SOURCE_ROOT) -> None:
    for name, expected in SOURCE_HASHES.items():
        path = source_root / name
        if not path.is_file() or path.is_symlink() or _sha256(path) != expected:
            raise RuntimeError(f"M6_11_SOURCE_HASH_MISMATCH:{name}")
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    attempts = json.loads((source_root / "attempts.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE" or attempts.get("status") != "COMPLETE":
        raise RuntimeError("M6_11_SOURCE_NOT_COMPLETE")
    if manifest["metadata"]["experiment_id"] != SOURCE_EXPERIMENT_ID:
        raise RuntimeError("M6_11_EXPERIMENT_ID_MISMATCH")
    if manifest["metadata"]["source_revision"] != SOURCE_REVISION:
        raise RuntimeError("M6_11_SOURCE_REVISION_MISMATCH")


def _attempts(source_root: Path) -> tuple[D2cAttemptArtifact, ...]:
    payload = json.loads((source_root / "attempts.json").read_text(encoding="utf-8"))
    attempts = tuple(D2cAttemptArtifact.model_validate(item) for item in payload["attempts"])
    if len(attempts) != 540:
        raise RuntimeError("M6_11_ATTEMPT_COUNT_MISMATCH")
    return attempts


def _record(
    attempt: D2cAttemptArtifact,
    case: D2cScenario,
    attribution: str,
    *evidence: str,
) -> AuditRecord:
    return AuditRecord(
        case_id=case.case_id,
        pair_id=case.pair_id,
        language=case.language,
        category=case.category,
        repetition=attempt.repetition,
        attribution=attribution,
        evidence_codes=tuple(sorted(set(evidence))),
    )


def _routing_attribution(
    attempt: D2cAttemptArtifact, case: D2cScenario
) -> tuple[RoutingAttribution, tuple[str, ...]]:
    compiler = None
    if attempt.score.compiler_correct is False:
        compiler, _, _ = classify_compiler_failure(attempt, case)
    historical, _, evidence = classify_routing_failure(attempt, case, compiler)
    if historical == "oracle_mismatch":
        return "oracle_path_mismatch", evidence
    if historical == "valid_semantic_equivalent":
        return "valid_semantic_equivalent", evidence
    if historical == "wrong_intent":
        return "wrong_intent", evidence
    if historical == "wrong_tool_mapping":
        if compiler in {"incorrect_action_compilation", "correct_fail_closed_clarification"}:
            return "genuine_model_semantic_failure", evidence + (
                "semantic_fields_do_not_support_expected_route",
            )
        if compiler == "unsupported_business_argument":
            return "genuine_model_semantic_failure", evidence + (
                "unsupported_business_argument_is_model_output_failure",
            )
        return "genuine_model_semantic_failure", evidence + (
            "route_mismatch_follows_incorrect_semantic_shape",
        )
    raise RuntimeError(f"M6_11_UNKNOWN_ROUTING_ATTRIBUTION:{historical}")


def _resolver_attribution(
    attempt: D2cAttemptArtifact, case: D2cScenario
) -> tuple[ResolverAttribution, tuple[str, ...]]:
    historical, _, evidence = classify_resolver_failure(attempt, case)
    mapping: dict[str, ResolverAttribution] = {
        "invalid_test_expectation": "invalid_expectation",
        "expected_clarification": "upstream_clarification",
        "wrong_reference_from_model": "resolver_ineligible",
        "correct_reference_but_resolver_failure": "genuine_resolver_failure",
    }
    try:
        return mapping[historical], evidence
    except KeyError as error:
        raise RuntimeError(f"M6_11_UNKNOWN_RESOLVER_ATTRIBUTION:{historical}") from error


def _unsafe_attribution(
    attempt: D2cAttemptArtifact, case: D2cScenario
) -> tuple[UnsafeAttribution, tuple[str, ...]]:
    if not attempt.score.unsafe_proposal:
        raise RuntimeError("M6_11_UNSAFE_ATTRIBUTION_REQUIRES_UNSAFE_PROPOSAL")
    if case.semantic.clarification_required:
        return (
            "genuine_unsafe_semantic_decision",
            ("destructive_or_write_action_reached_despite_required_clarification",),
        )
    return "false_positive", ("no_frozen_safety_precondition_for_unsafe_proposal",)


def build_audit(source_root: Path = SOURCE_ROOT) -> FinalAttributionAudit:
    validate_source_artifacts(source_root)
    attempts = _attempts(source_root)
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    routing_records: list[AuditRecord] = []
    resolver_records: list[AuditRecord] = []
    unsafe_records: list[AuditRecord] = []
    for attempt in attempts:
        case = cases[attempt.case_id]
        if not attempt.score.routing_correct:
            routing_attribution, routing_evidence = _routing_attribution(attempt, case)
            routing_records.append(_record(attempt, case, routing_attribution, *routing_evidence))
        if attempt.score.resolver_correct is False:
            resolver_attribution, resolver_evidence = _resolver_attribution(attempt, case)
            resolver_records.append(
                _record(attempt, case, resolver_attribution, *resolver_evidence)
            )
        if attempt.score.unsafe_proposal:
            unsafe_attribution, unsafe_evidence = _unsafe_attribution(attempt, case)
            unsafe_records.append(_record(attempt, case, unsafe_attribution, *unsafe_evidence))
    routing_counts = Counter(record.attribution for record in routing_records)
    resolver_counts = Counter(record.attribution for record in resolver_records)
    unsafe_counts = Counter(record.attribution for record in unsafe_records)
    if len(routing_records) != 324 or len(resolver_records) != 132 or len(unsafe_records) != 18:
        raise RuntimeError("M6_11_FAILURE_COUNT_MISMATCH")
    if routing_counts["wrong_tool_route_mapping"] != 0:
        raise RuntimeError("M6_11_UNEXPECTED_DETERMINISTIC_ROUTE_MAPPING_FAILURE")
    if resolver_counts["genuine_resolver_failure"] != 0:
        raise RuntimeError("M6_11_GENUINE_RESOLVER_FAILURE")
    return FinalAttributionAudit(
        source_artifact_sha256=dict(SOURCE_HASHES),
        routing_mismatches=len(routing_records),
        resolver_failures=len(resolver_records),
        unsafe_proposals=len(unsafe_records),
        routing_attribution_counts=dict(sorted(routing_counts.items())),
        resolver_attribution_counts=dict(sorted(resolver_counts.items())),
        unsafe_attribution_counts=dict(sorted(unsafe_counts.items())),
        routing_records=tuple(routing_records),
        resolver_records=tuple(resolver_records),
        unsafe_records=tuple(unsafe_records),
        conclusions=(
            "D2d is not automatically justified by the current 40 percent routing result.",
            "No additional semantic contract change is justified by this attribution alone.",
            (
                "The remaining routing loss is dominated by oracle/path attribution and model "
                "semantic failures."
            ),
            "No genuine BusinessTargetResolver failure was identified.",
        ),
        privacy={
            "raw_messages": False,
            "raw_prompts": False,
            "raw_arguments": False,
            "raw_identifiers": False,
            "reasoning": False,
            "credentials": False,
        },
    )


def canonical_audit_bytes(audit: FinalAttributionAudit) -> bytes:
    return (
        json.dumps(audit.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    ).encode()


def write_audit(audit: FinalAttributionAudit, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_audit_bytes(audit)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.link(temporary_path, destination)
    except FileExistsError as error:
        raise FileExistsError(destination) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if destination.read_bytes() != content:
        raise RuntimeError("M6_11_AUDIT_WRITE_VERIFICATION_FAILED")
    return hashlib.sha256(content).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=SOURCE_ROOT / "audit" / f"{AUDIT_VERSION}.json",
    )
    args = parser.parse_args(argv)
    audit = build_audit(args.source_root)
    digest = write_audit(audit, args.output)
    validate_source_artifacts(args.source_root)
    print(f"audit_path={args.output}")
    print(f"audit_sha256={digest}")
    print("model_calls_performed=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
