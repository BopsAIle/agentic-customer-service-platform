"""Offline attribution audit for the immutable canonical M6/D2c evidence."""

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

from app.agent.schemas import Intent
from evaluation.d2c_runner import D2cAttemptArtifact
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases

AUDIT_VERSION = "d2c_attribution_audit_v1"
SOURCE_EXPERIMENT_ID = "d2c_semantic_v3_20260813T221348Z"
SOURCE_REVISION = "012d42cac6e0ed0a20b45aa0d0c742b15cacad96"
SOURCE_ROOT = Path("artifacts/live-eval/production-robustness/d2c_semantic_v3_20260813T221348Z")
SOURCE_HASHES = {
    "manifest.json": "7a39fe0c8a4e40b0e4e209ee4c7bc66e2ae9ae541963be74b96be67863ed9df5",
    "attempts.json": "b84d8d25d34b510540e9b191bdf547ef92640d7cd058b49f074581ce8caaac0e",
    "summary.json": "b9cf64c9289c64be0799b540304d60bd8688efcf5f57aa19bd1e9583080c9848",
    "summary.md": "c5d2886fa5bc812220237b23c0aaac8f4801d3d79bceb169ea6396ee01432f46",
}

RoutingAttribution = Literal[
    "wrong_intent",
    "valid_semantic_equivalent",
    "wrong_tool_mapping",
    "oracle_mismatch",
]
ResolverAttribution = Literal[
    "wrong_reference_from_model",
    "correct_reference_but_resolver_failure",
    "expected_clarification",
    "invalid_test_expectation",
]
CompilerAttribution = Literal[
    "incorrect_action_compilation",
    "correct_fail_closed_clarification",
    "unsupported_business_argument",
    "oracle_mismatch",
]
RootOwner = Literal["model_semantics", "deterministic_pipeline", "evaluation_oracle"]

_VALID_EQUIVALENT_PAIR_INTENTS = {
    ("std-subscription-question", Intent.CAPABILITY_QUESTION.value),
}
_KNOWLEDGE_ACTION_ORACLE_INTENTS = {
    Intent.REFUND_ELIGIBILITY.value,
    Intent.CANCELLATION_EXPLANATION.value,
}
_PRE_PROVIDER_FAILURES = {
    "provider_failure",
    "provider_timeout",
    "schema_failure",
    "structured_output_failure",
}


class AttributionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    pair_id: str
    language: Literal["en", "tr"]
    category: str
    repetition: int
    attribution: str
    root_owner: RootOwner
    evidence_codes: tuple[str, ...]


class D2cAttributionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: Literal["d2c_attribution_audit_v1"] = "d2c_attribution_audit_v1"
    status: Literal["COMPLETE"] = "COMPLETE"
    source_experiment_id: Literal["d2c_semantic_v3_20260813T221348Z"] = (
        "d2c_semantic_v3_20260813T221348Z"
    )
    source_revision: Literal["012d42cac6e0ed0a20b45aa0d0c742b15cacad96"] = (
        "012d42cac6e0ed0a20b45aa0d0c742b15cacad96"
    )
    source_artifact_sha256: dict[str, str]
    model_calls_performed: Literal[0] = 0
    model_outputs_changed: Literal[False] = False
    historical_artifacts_changed: Literal[False] = False
    routing_failures: int
    resolver_failures: int
    compiler_failures: int
    routing_attribution_counts: dict[str, int]
    resolver_attribution_counts: dict[str, int]
    compiler_attribution_counts: dict[str, int]
    root_owner_counts: dict[str, int]
    routing_records: tuple[AttributionRecord, ...]
    resolver_records: tuple[AttributionRecord, ...]
    compiler_records: tuple[AttributionRecord, ...]
    evidence_limitations: tuple[str, ...]
    privacy: dict[str, bool]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source_artifacts(source_root: Path = SOURCE_ROOT) -> None:
    """Fail closed unless every immutable D2c source artifact is byte-identical."""

    for name, expected in SOURCE_HASHES.items():
        path = source_root / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"D2C_AUDIT_SOURCE_MISSING:{name}")
        if _sha256(path) != expected:
            raise RuntimeError(f"D2C_AUDIT_SOURCE_HASH_MISMATCH:{name}")
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    attempts = json.loads((source_root / "attempts.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE" or attempts.get("status") != "COMPLETE":
        raise RuntimeError("D2C_AUDIT_SOURCE_NOT_COMPLETE")
    if manifest["metadata"]["experiment_id"] != SOURCE_EXPERIMENT_ID:
        raise RuntimeError("D2C_AUDIT_EXPERIMENT_ID_MISMATCH")
    if manifest["metadata"]["source_revision"] != SOURCE_REVISION:
        raise RuntimeError("D2C_AUDIT_SOURCE_REVISION_MISMATCH")


def _attempts(source_root: Path) -> tuple[D2cAttemptArtifact, ...]:
    payload = json.loads((source_root / "attempts.json").read_text(encoding="utf-8"))
    attempts = tuple(D2cAttemptArtifact.model_validate(item) for item in payload["attempts"])
    if len(attempts) != 540:
        raise RuntimeError("D2C_AUDIT_ATTEMPT_COUNT_MISMATCH")
    return attempts


def _record(
    attempt: D2cAttemptArtifact,
    case: D2cScenario,
    attribution: str,
    owner: RootOwner,
    *evidence: str,
) -> AttributionRecord:
    return AttributionRecord(
        case_id=case.case_id,
        pair_id=case.pair_id,
        language=case.language,
        category=case.category,
        repetition=attempt.repetition,
        attribution=attribution,
        root_owner=owner,
        evidence_codes=tuple(sorted(set(evidence))),
    )


def classify_compiler_failure(
    attempt: D2cAttemptArtifact, case: D2cScenario
) -> tuple[CompilerAttribution, RootOwner, tuple[str, ...]]:
    """Attribute a historical compiler false score without changing that score."""

    expected = case.deterministic.compiler
    actual = attempt.actual_compiler
    if (
        expected == "clarification"
        and actual == "action"
        and bool(case.semantic.forbidden_invented_fields)
    ):
        return (
            "unsupported_business_argument",
            "model_semantics",
            ("model_action_uses_user_absent_forbidden_field",),
        )
    if actual in {"clarification", "safe_failure"} and expected != actual:
        return (
            "correct_fail_closed_clarification",
            "model_semantics",
            ("deterministic_layer_rejected_incomplete_or_incompatible_semantics",),
        )
    if (
        attempt.actual_intent in _KNOWLEDGE_ACTION_ORACLE_INTENTS
        and attempt.score.intent_correct is True
        and actual == "knowledge"
        and expected == "action"
    ):
        return (
            "oracle_mismatch",
            "evaluation_oracle",
            ("frozen_compiler_routes_intent_to_knowledge", "oracle_requires_hybrid_action"),
        )
    return (
        "incorrect_action_compilation",
        "model_semantics",
        ("compiled_outcome_does_not_match_task_oracle",),
    )


def classify_resolver_failure(
    attempt: D2cAttemptArtifact, case: D2cScenario
) -> tuple[ResolverAttribution, RootOwner, tuple[str, ...]]:
    """Separate reference quality, resolver behavior, and invalid resolver eligibility."""

    if attempt.score.semantic_target_correct is False:
        return (
            "wrong_reference_from_model",
            "model_semantics",
            ("semantic_target_mismatch_precedes_resolution",),
        )
    expected = case.deterministic.resolver
    actual = attempt.actual_resolver
    if expected == "blocked_before_resolver":
        return (
            "expected_clarification",
            "evaluation_oracle",
            (
                "resolver_not_invoked",
                "clarification_path_is_not_resolver_failure",
                f"actual_resolver_{actual}",
            ),
        )
    if expected == "not_found":
        return (
            "invalid_test_expectation",
            "evaluation_oracle",
            ("existence_and_scope_belong_to_business_validation_not_reference_resolver",),
        )
    if expected == "explicit_ticket_passthrough":
        return (
            "invalid_test_expectation",
            "evaluation_oracle",
            ("business_target_resolver_resolves_order_references_only",),
        )
    if actual == "not_applicable" and expected == "explicit_order_passthrough":
        return (
            "invalid_test_expectation",
            "evaluation_oracle",
            ("upstream_route_did_not_invoke_resolver", "stage_ineligible_not_resolver_failure"),
        )
    return (
        "correct_reference_but_resolver_failure",
        "deterministic_pipeline",
        ("eligible_reference_resolved_incorrectly",),
    )


def classify_routing_failure(
    attempt: D2cAttemptArtifact,
    case: D2cScenario,
    compiler_classification: CompilerAttribution | None,
) -> tuple[RoutingAttribution, RootOwner, tuple[str, ...]]:
    """Classify every historical routing miss under the requested four-way taxonomy."""

    labels = set(attempt.score.failure_labels)
    if labels & _PRE_PROVIDER_FAILURES:
        return (
            "oracle_mismatch",
            "evaluation_oracle",
            ("expected_safe_failure_path_cannot_require_schema_valid_semantics",),
        )
    if attempt.score.intent_correct is False:
        if (case.pair_id, attempt.actual_intent or "") in _VALID_EQUIVALENT_PAIR_INTENTS:
            return (
                "valid_semantic_equivalent",
                "evaluation_oracle",
                ("bounded_user_level_intent_equivalence",),
            )
        return ("wrong_intent", "model_semantics", ("intent_not_in_accepted_intents",))
    if compiler_classification == "oracle_mismatch":
        return (
            "oracle_mismatch",
            "evaluation_oracle",
            ("compiler_route_is_frozen_but_oracle_requires_unsupported_route",),
        )
    if compiler_classification is not None:
        owner: RootOwner = (
            "model_semantics"
            if compiler_classification
            in {
                "incorrect_action_compilation",
                "unsupported_business_argument",
                "correct_fail_closed_clarification",
            }
            else "deterministic_pipeline"
        )
        return (
            "wrong_tool_mapping",
            owner,
            (f"compiler_attribution_{compiler_classification}",),
        )
    if (
        attempt.score.semantic_target_correct is False
        or attempt.score.clarification_correct is False
        or attempt.score.request_type_correct is False
    ):
        return (
            "wrong_tool_mapping",
            "model_semantics",
            ("semantic_or_clarification_shape_does_not_support_expected_route",),
        )
    return (
        "oracle_mismatch",
        "evaluation_oracle",
        (
            "semantic_outcome_correct_but_execution_path_rejected",
            "stage_enum_or_path_realization_mismatch",
        ),
    )


def build_audit(source_root: Path = SOURCE_ROOT) -> D2cAttributionAudit:
    validate_source_artifacts(source_root)
    attempts = _attempts(source_root)
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    routing_records: list[AttributionRecord] = []
    resolver_records: list[AttributionRecord] = []
    compiler_records: list[AttributionRecord] = []

    for attempt in attempts:
        case = cases[attempt.case_id]
        compiler_result: CompilerAttribution | None = None
        if attempt.score.compiler_correct is False:
            compiler_result, owner, evidence = classify_compiler_failure(attempt, case)
            compiler_records.append(_record(attempt, case, compiler_result, owner, *evidence))
        if attempt.score.resolver_correct is False:
            resolver_result, owner, evidence = classify_resolver_failure(attempt, case)
            resolver_records.append(_record(attempt, case, resolver_result, owner, *evidence))
        if not attempt.score.routing_correct:
            routing_result, owner, evidence = classify_routing_failure(
                attempt, case, compiler_result
            )
            routing_records.append(_record(attempt, case, routing_result, owner, *evidence))

    routing_counts = Counter(record.attribution for record in routing_records)
    resolver_counts = Counter(record.attribution for record in resolver_records)
    compiler_counts = Counter(record.attribution for record in compiler_records)
    owner_counts = Counter(
        record.root_owner
        for records in (routing_records, resolver_records, compiler_records)
        for record in records
    )
    if len(routing_records) != 332 or len(resolver_records) != 145 or len(compiler_records) != 64:
        raise RuntimeError("D2C_AUDIT_HISTORICAL_FAILURE_COUNT_MISMATCH")
    return D2cAttributionAudit(
        source_artifact_sha256=dict(SOURCE_HASHES),
        routing_failures=len(routing_records),
        resolver_failures=len(resolver_records),
        compiler_failures=len(compiler_records),
        routing_attribution_counts=dict(sorted(routing_counts.items())),
        resolver_attribution_counts=dict(sorted(resolver_counts.items())),
        compiler_attribution_counts=dict(sorted(compiler_counts.items())),
        root_owner_counts=dict(sorted(owner_counts.items())),
        routing_records=tuple(routing_records),
        resolver_records=tuple(resolver_records),
        compiler_records=tuple(compiler_records),
        evidence_limitations=(
            "raw model arguments were intentionally not persisted",
            (
                "unsupported business arguments are attributable only where the frozen oracle "
                "marks the field forbidden"
            ),
            (
                "the compile-only D2c observer did not execute business validation or policy "
                "per measured attempt"
            ),
            "latency and safety metrics are not rescored by this attribution audit",
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


def canonical_audit_bytes(audit: D2cAttributionAudit) -> bytes:
    return (
        json.dumps(
            audit.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode()


def write_audit(audit: D2cAttributionAudit, destination: Path) -> str:
    """Atomically create one immutable audit artifact without touching source evidence."""

    if destination.exists():
        raise FileExistsError("D2c audit artifact already exists")
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
        raise FileExistsError("D2c audit artifact already exists") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if destination.read_bytes() != content:
        raise RuntimeError("D2C_AUDIT_WRITE_VERIFICATION_FAILED")
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
