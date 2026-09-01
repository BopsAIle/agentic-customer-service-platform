"""Offline compiler/oracle alignment audit for canonical M6/D2c evidence."""

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
from evaluation.d2c_audit import AUDIT_VERSION as ATTRIBUTION_AUDIT_VERSION
from evaluation.d2c_audit import SOURCE_HASHES as D2C_SOURCE_HASHES
from evaluation.d2c_audit import SOURCE_ROOT as D2C_SOURCE_ROOT
from evaluation.d2c_audit import validate_source_artifacts
from evaluation.d2c_runner import D2cAttemptArtifact
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases
from evaluation.provenance import hash_prompt_bytes

COMPILER_AUDIT_VERSION = "d2c_compiler_alignment_audit_v1"
SOURCE_EVIDENCE_ROOT = D2C_SOURCE_ROOT
SOURCE_ARTIFACT_HASHES = dict(D2C_SOURCE_HASHES)
ATTRIBUTION_AUDIT_NAME = f"{ATTRIBUTION_AUDIT_VERSION}.json"
ATTRIBUTION_AUDIT_SHA256 = "650d54019ed055bc28c548fe525c01a34902c6384bc954cda5d1ee4862b41ef4"

CompilerAlignmentClassification = Literal[
    "model_semantic_decision_incorrect",
    "compiler_mapping_missing",
    "correct_fail_closed_behavior",
    "oracle_expectation_mismatch",
    "unsupported_business_argument_handling",
]
RootOwner = Literal[
    "model_semantics",
    "decision_compiler",
    "evaluation_oracle",
    "business_argument_boundary",
]

CLASSIFICATIONS: tuple[CompilerAlignmentClassification, ...] = (
    "model_semantic_decision_incorrect",
    "compiler_mapping_missing",
    "correct_fail_closed_behavior",
    "oracle_expectation_mismatch",
    "unsupported_business_argument_handling",
)
TARGET_HISTORICAL_ATTRIBUTIONS = frozenset({"incorrect_action_compilation", "oracle_mismatch"})
HYBRID_INTENTS = frozenset({Intent.REFUND_ELIGIBILITY.value, Intent.CANCELLATION_EXPLANATION.value})


class CompilerAlignmentRecord(BaseModel):
    """One privacy-safe re-attribution of a frozen compiler-score failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    pair_id: str
    language: Literal["en", "tr"]
    category: str
    repetition: int
    historical_attribution: Literal["incorrect_action_compilation", "oracle_mismatch"]
    classification: CompilerAlignmentClassification
    root_owner: RootOwner
    accepted_intents: tuple[str, ...]
    accepted_request_types: tuple[str, ...]
    expected_clarification: bool
    expected_compiler_outcome: str
    expected_execution_paths: tuple[str, ...]
    actual_intent: str | None
    actual_request_type: str | None
    actual_target_variant: str | None
    actual_clarification: bool | None
    actual_compiler_outcome: str | None
    actual_resolver_outcome: str | None
    evidence_codes: tuple[str, ...]


class D2cCompilerAlignmentAudit(BaseModel):
    """Canonical result of the offline M6.3 compiler/oracle audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: Literal["d2c_compiler_alignment_audit_v1"] = "d2c_compiler_alignment_audit_v1"
    status: Literal["COMPLETE"] = "COMPLETE"
    source_experiment_id: Literal["d2c_semantic_v3_20260813T221348Z"] = (
        "d2c_semantic_v3_20260813T221348Z"
    )
    source_revision: Literal["012d42cac6e0ed0a20b45aa0d0c742b15cacad96"] = (
        "012d42cac6e0ed0a20b45aa0d0c742b15cacad96"
    )
    source_artifact_sha256: dict[str, str]
    source_attribution_audit_version: Literal["d2c_attribution_audit_v1"] = (
        "d2c_attribution_audit_v1"
    )
    source_attribution_audit_sha256: str
    model_calls_performed: Literal[0] = 0
    model_outputs_changed: Literal[False] = False
    historical_artifacts_changed: Literal[False] = False
    production_runtime_changed: Literal[False] = False
    analyzed_incorrect_action_compilation: int
    analyzed_compiler_oracle_mismatches: int
    analyzed_total: int
    classification_counts: dict[str, int]
    records: tuple[CompilerAlignmentRecord, ...]
    conclusions: tuple[str, ...]
    evidence_limitations: tuple[str, ...]
    privacy: dict[str, bool]


def _sha256(path: Path) -> str:
    return hash_prompt_bytes(path.read_bytes())


def _load_attribution_records(source_root: Path) -> tuple[dict[str, object], ...]:
    path = source_root / "audit" / ATTRIBUTION_AUDIT_NAME
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("D2C_COMPILER_AUDIT_ATTRIBUTION_SOURCE_MISSING")
    if _sha256(path) != ATTRIBUTION_AUDIT_SHA256:
        raise RuntimeError("D2C_COMPILER_AUDIT_ATTRIBUTION_SOURCE_HASH_MISMATCH")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "COMPLETE":
        raise RuntimeError("D2C_COMPILER_AUDIT_ATTRIBUTION_SOURCE_NOT_COMPLETE")
    if payload.get("audit_version") != ATTRIBUTION_AUDIT_VERSION:
        raise RuntimeError("D2C_COMPILER_AUDIT_ATTRIBUTION_VERSION_MISMATCH")
    records = tuple(
        record
        for record in payload.get("compiler_records", ())
        if record.get("attribution") in TARGET_HISTORICAL_ATTRIBUTIONS
    )
    historical_counts = Counter(record.get("attribution") for record in records)
    if historical_counts != Counter({"incorrect_action_compilation": 36, "oracle_mismatch": 12}):
        raise RuntimeError("D2C_COMPILER_AUDIT_TARGET_COUNT_MISMATCH")
    return records


def _load_attempts(source_root: Path) -> dict[tuple[str, int], D2cAttemptArtifact]:
    payload = json.loads((source_root / "attempts.json").read_text(encoding="utf-8"))
    attempts = {
        (item.case_id, item.repetition): item
        for item in (D2cAttemptArtifact.model_validate(raw) for raw in payload.get("attempts", ()))
    }
    if len(attempts) != 540:
        raise RuntimeError("D2C_COMPILER_AUDIT_ATTEMPT_COUNT_MISMATCH")
    return attempts


def classify_alignment_failure(
    attempt: D2cAttemptArtifact,
    case: D2cScenario,
) -> tuple[CompilerAlignmentClassification, RootOwner, tuple[str, ...]]:
    """Assign one stage-owned cause without changing historical scoring."""

    accepted_intents = {intent.value for intent in case.semantic.accepted_intents}
    accepted_request_types = {
        request_type.value for request_type in case.semantic.accepted_request_types
    }
    if (
        attempt.actual_intent in HYBRID_INTENTS
        and attempt.actual_intent in accepted_intents
        and attempt.actual_target_variant in case.semantic.accepted_target_variants
        and attempt.actual_compiler == "knowledge"
        and case.deterministic.compiler == "action"
        and any(
            path.startswith("get_order_then_retrieve_")
            for path in case.deterministic.accepted_execution_paths
        )
    ):
        return (
            "compiler_mapping_missing",
            "decision_compiler",
            (
                "hybrid_intent_and_target_are_sufficient_for_state_plus_policy",
                "legacy_runtime_supports_knowledge_and_action",
                "semantic_compiler_routes_hybrid_intent_to_knowledge_only",
            ),
        )
    if attempt.actual_compiler in {
        "clarification",
        "safe_failure",
    } and case.deterministic.compiler not in {"clarification", "safe_failure"}:
        return (
            "correct_fail_closed_behavior",
            "business_argument_boundary",
            ("compiler_refused_incomplete_or_incompatible_action_semantics",),
        )
    if (
        case.semantic.forbidden_invented_fields
        and attempt.actual_compiler == "action"
        and case.deterministic.compiler == "clarification"
    ):
        return (
            "unsupported_business_argument_handling",
            "business_argument_boundary",
            ("action_constructed_despite_user_absent_forbidden_business_field",),
        )
    semantic_mismatch = (
        attempt.actual_intent not in accepted_intents
        or attempt.actual_request_type not in accepted_request_types
        or attempt.actual_clarification != case.semantic.clarification_required
        or attempt.score.semantic_target_correct is False
    )
    if semantic_mismatch:
        evidence = ["compiler_faithfully_realized_incorrect_model_semantics"]
        if attempt.actual_intent not in accepted_intents:
            evidence.append("intent_not_accepted")
        if attempt.actual_request_type not in accepted_request_types:
            evidence.append("request_type_not_accepted")
        if attempt.actual_clarification != case.semantic.clarification_required:
            evidence.append("clarification_flag_mismatch")
        if attempt.score.semantic_target_correct is False:
            evidence.append("semantic_target_mismatch")
        return (
            "model_semantic_decision_incorrect",
            "model_semantics",
            tuple(sorted(evidence)),
        )
    return (
        "oracle_expectation_mismatch",
        "evaluation_oracle",
        ("semantics_and_compiler_are_consistent_but_frozen_oracle_rejects_route",),
    )


def _record(
    historical: dict[str, object],
    attempt: D2cAttemptArtifact,
    case: D2cScenario,
) -> CompilerAlignmentRecord:
    classification, owner, evidence = classify_alignment_failure(attempt, case)
    historical_attribution = historical["attribution"]
    if historical_attribution not in TARGET_HISTORICAL_ATTRIBUTIONS:
        raise RuntimeError("D2C_COMPILER_AUDIT_UNEXPECTED_HISTORICAL_ATTRIBUTION")
    return CompilerAlignmentRecord(
        case_id=case.case_id,
        pair_id=case.pair_id,
        language=case.language,
        category=case.category,
        repetition=attempt.repetition,
        historical_attribution=historical_attribution,
        classification=classification,
        root_owner=owner,
        accepted_intents=tuple(intent.value for intent in case.semantic.accepted_intents),
        accepted_request_types=tuple(
            request_type.value for request_type in case.semantic.accepted_request_types
        ),
        expected_clarification=case.semantic.clarification_required,
        expected_compiler_outcome=case.deterministic.compiler,
        expected_execution_paths=case.deterministic.accepted_execution_paths,
        actual_intent=attempt.actual_intent,
        actual_request_type=attempt.actual_request_type,
        actual_target_variant=attempt.actual_target_variant,
        actual_clarification=attempt.actual_clarification,
        actual_compiler_outcome=attempt.actual_compiler,
        actual_resolver_outcome=attempt.actual_resolver,
        evidence_codes=evidence,
    )


def build_audit(source_root: Path = SOURCE_EVIDENCE_ROOT) -> D2cCompilerAlignmentAudit:
    """Build the deterministic audit from immutable D2c and M6.2 evidence."""

    validate_source_artifacts(source_root)
    historical_records = _load_attribution_records(source_root)
    attempts = _load_attempts(source_root)
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    records_list: list[CompilerAlignmentRecord] = []
    for historical in historical_records:
        case_id = historical.get("case_id")
        repetition = historical.get("repetition")
        if not isinstance(case_id, str) or not isinstance(repetition, int):
            raise RuntimeError("D2C_COMPILER_AUDIT_RECORD_IDENTITY_INVALID")
        records_list.append(_record(historical, attempts[(case_id, repetition)], cases[case_id]))
    records = tuple(records_list)
    counts = Counter(record.classification for record in records)
    complete_counts = {classification: counts[classification] for classification in CLASSIFICATIONS}
    expected_counts = {
        "model_semantic_decision_incorrect": 36,
        "compiler_mapping_missing": 12,
        "correct_fail_closed_behavior": 0,
        "oracle_expectation_mismatch": 0,
        "unsupported_business_argument_handling": 0,
    }
    if complete_counts != expected_counts:
        raise RuntimeError("D2C_COMPILER_AUDIT_CLASSIFICATION_COUNT_MISMATCH")
    return D2cCompilerAlignmentAudit(
        source_artifact_sha256=dict(SOURCE_ARTIFACT_HASHES),
        source_attribution_audit_sha256=ATTRIBUTION_AUDIT_SHA256,
        analyzed_incorrect_action_compilation=36,
        analyzed_compiler_oracle_mismatches=12,
        analyzed_total=len(records),
        classification_counts=complete_counts,
        records=records,
        conclusions=(
            (
                "The 36 historical incorrect-action-compilation scores are model semantic "
                "decision failures, not DecisionCompiler mapping defects."
            ),
            (
                "The 12 historical compiler-oracle mismatches expose a missing semantic "
                "compiler realization for state-aware knowledge-and-action intents."
            ),
            (
                "No production behavior, oracle, contract, prompt, schema, or historical "
                "artifact was changed by this audit."
            ),
        ),
        evidence_limitations=(
            "Raw model arguments were intentionally not persisted and were not reconstructed.",
            (
                "This audit attributes frozen evidence; it does not remediate or prospectively "
                "validate the missing compiler mapping."
            ),
            "Safety and latency metrics are unchanged and are not rescored.",
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


def canonical_audit_bytes(audit: D2cCompilerAlignmentAudit) -> bytes:
    return (
        json.dumps(
            audit.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode()


def write_audit(audit: D2cCompilerAlignmentAudit, destination: Path) -> str:
    """Atomically publish one immutable, read-back-verified audit artifact."""

    if destination.exists():
        raise FileExistsError("D2c compiler audit artifact already exists")
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
        raise FileExistsError("D2c compiler audit artifact already exists") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if destination.read_bytes() != content:
        raise RuntimeError("D2C_COMPILER_AUDIT_WRITE_VERIFICATION_FAILED")
    return hashlib.sha256(content).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_EVIDENCE_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=SOURCE_EVIDENCE_ROOT / "audit" / f"{COMPILER_AUDIT_VERSION}.json",
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
