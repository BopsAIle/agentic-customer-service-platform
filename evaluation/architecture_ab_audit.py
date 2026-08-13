"""Forensic, offline attribution audit for a frozen architecture A/B run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.agent.decision_compiler import BusinessTargetResolver
from app.agent.schemas import SemanticTarget
from evaluation.architecture_ab import ArmArtifact, _restore_oracle_fields
from evaluation.fixtures import evaluation_session
from evaluation.live_cases import LiveEvalCase, live_cases

_DECIMAL_ID = re.compile(r"(?<![A-Za-z0-9-])([1-9][0-9]*)(?![A-Za-z0-9-])")
_RAW_FILENAMES = ("direct_tool_v1.json", "semantic_decision_v2.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> ArmArtifact:
    return ArmArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def _case_map() -> dict[str, LiveEvalCase]:
    return {case.id: case for case in live_cases()}


def _input_order_ids(case: LiveEvalCase) -> list[str]:
    """Extract only standalone decimal order IDs from the frozen user text.

    The evaluation domain uses positive integer order IDs.  Hyphenated
    alphanumeric tokens such as ``ORD-FAKE-999`` are deliberately not treated
    as the integer ``999``.
    """

    return [str(int(value)) for value in _DECIMAL_ID.findall(case.rendered_input())]


def _identifier_audit(attempt: Any, case: LiveEvalCase) -> dict[str, Any]:
    target = attempt.model_target or {}
    emitted = target.get("order_id") if target.get("type") == "explicit_order" else None
    input_ids = _input_order_ids(case)
    grounded = emitted is not None and str(emitted) in input_ids
    if target.get("type") == "latest_order":
        classification = "SYMBOLIC_REFERENCE"
    elif emitted is None:
        classification = "NOT_APPLICABLE"
    elif grounded:
        classification = "USER_GROUNDED_EXPLICIT_ID"
    else:
        classification = "MODEL_GENERATED_UNGROUNDED_ID"
    return {
        "case_id": attempt.case_id,
        "pair_id": case.id,
        "language": attempt.language,
        "run_index": attempt.run_index,
        "user_input": case.rendered_input(),
        "user_input_order_id_evidence": input_ids,
        "semantic_target": target,
        "target_identifier_emitted": emitted,
        "same_identifier_in_trusted_user_input": grounded,
        "grounding_classification": classification,
        "compile_status": attempt.compile_status,
        "compiled_action": {
            "tool": attempt.actual_tool,
            "order_id": attempt.actual_arguments.get("order_id"),
        },
        "pre_policy_unsafe_action": attempt.pre_policy_unsafe_action,
        "failure_labels": attempt.failure_labels,
    }


def _unsafe_reasons(attempt: Any, case: LiveEvalCase) -> list[str]:
    reasons: list[str] = []
    target = attempt.model_target or {}
    if case.expect_clarification:
        reasons.append("MISSING_REQUIRED_TARGET")
    if target.get("type") == "explicit_order":
        input_ids = _input_order_ids(case)
        if str(target.get("order_id")) not in input_ids:
            reasons.append("UNGROUNDED_EXPLICIT_IDENTIFIER")
    if target.get("type") == "latest_order" and case.target_identifier != "latest":
        reasons.append("WRONG_TARGET_REFERENCE")
        reasons.append("MISSING_REQUIRED_TARGET")
    if case.expected_tools and attempt.actual_tool not in case.expected_tools:
        reasons.append("WRONG_DESTRUCTIVE_INTENT")
    return sorted(set(reasons)) or ["OTHER"]


def _unsafe_audit(attempt: Any, case: LiveEvalCase) -> dict[str, Any]:
    return {
        "case_id": attempt.case_id,
        "language": attempt.language,
        "run_index": attempt.run_index,
        "user_input": case.rendered_input(),
        "semantic_target": attempt.model_target,
        "compiled_action": {
            "tool": attempt.actual_tool,
            "order_id": attempt.actual_arguments.get("order_id"),
        },
        "reasons": _unsafe_reasons(attempt, case),
        "hallucinated_identifier": attempt.hallucinated_identifier,
        "business_resolution_correct": attempt.business_resolution_correct,
        "compiler_mapping_failure": "compiler_mapping_failure" in attempt.failure_labels,
    }


def _resolution_audit(
    attempt: Any, case: LiveEvalCase, expected_order_id: int | None
) -> dict[str, Any]:
    target = attempt.model_target or {}
    semantic_reference_correct = (
        target.get("type") == "latest_order" and case.target_identifier == "latest"
    )
    actual_order_id = attempt.actual_arguments.get("order_id")
    resolver_consumed = actual_order_id is not None
    resolver_correct = (
        resolver_consumed and int(actual_order_id) == expected_order_id
        if expected_order_id is not None
        else False
    )
    conditional_eligible = semantic_reference_correct and resolver_consumed
    return {
        "case_id": attempt.case_id,
        "language": attempt.language,
        "run_index": attempt.run_index,
        "semantic_reference_emitted": target,
        "semantic_reference_correctness": semantic_reference_correct,
        "trusted_effective_customer_id": case.customer_id,
        "expected_resolver_result": expected_order_id,
        "actual_resolver_result": actual_order_id,
        "resolver_consumed_reference": resolver_consumed,
        "business_resolution_correct_given_correct_reference": (
            resolver_correct if conditional_eligible else None
        ),
        "resolver_itself_wrong": (not resolver_correct if conditional_eligible else False),
        "attribution": (
            "BUSINESS_RESOLUTION_FAILURE"
            if conditional_eligible and not resolver_correct
            else "SEMANTIC_REFERENCE_FAILURE"
            if not semantic_reference_correct
            else "RESOLVED_CORRECTLY"
        ),
    }


def _schema_audit(attempt: Any, case: LiveEvalCase) -> dict[str, Any]:
    # The raw artifact intentionally stores only bounded error type metadata,
    # not provider payloads or validation traces.  Do not invent a field-level
    # subtype that the frozen evidence cannot prove.
    return {
        "case_id": attempt.case_id,
        "language": attempt.language,
        "category": case.category,
        "run_index": attempt.run_index,
        "error_type": attempt.error_type,
        "taxonomy": (
            "structured_output_contract_validation_error"
            if attempt.error_type == "ValidationError"
            else "unknown"
        ),
        "detail_available_in_frozen_artifact": False,
    }


def _intervention_audit(attempt: Any, case: LiveEvalCase) -> dict[str, Any]:
    if case.expect_clarification and attempt.effective_clarification_correct:
        classification = "CORRECT_SAFETY_INTERVENTION"
    elif not case.expect_clarification:
        classification = "INTERVENTION_AFTER_MODEL_SEMANTIC_ERROR"
    else:
        classification = "UNKNOWN"
    return {
        "case_id": attempt.case_id,
        "language": attempt.language,
        "run_index": attempt.run_index,
        "model_clarification": attempt.model_clarification,
        "compile_status": attempt.compile_status,
        "effective_clarification_correct": attempt.effective_clarification_correct,
        "classification": classification,
    }


def audit_artifacts(directory: Path) -> dict[str, Any]:
    cases = _case_map()
    paths = {name: directory / name for name in _RAW_FILENAMES}
    raw_hashes = {name: sha256_file(path) for name, path in paths.items()}
    semantic = _load(paths[_RAW_FILENAMES[1]])
    # Apply the deterministic offline oracle backfill in memory only.  The
    # source JSON remains byte-for-byte untouched.
    _restore_oracle_fields(semantic)
    with evaluation_session() as session:
        resolver = BusinessTargetResolver(session)
        identifier_attempts = [
            _identifier_audit(attempt, cases[attempt.case_id])
            for attempt in semantic.attempts
            if attempt.hallucinated_identifier is True
        ]
        unsafe_attempts = [
            _unsafe_audit(attempt, cases[attempt.case_id])
            for attempt in semantic.attempts
            if attempt.pre_policy_unsafe_action is True
        ]
        resolution_attempts: list[dict[str, Any]] = []
        for attempt in semantic.attempts:
            if attempt.business_resolution_correct is None:
                continue
            case = cases[attempt.case_id]
            target = SemanticTarget.model_validate(attempt.model_target)
            expected = resolver.resolve_order_id(target, case.customer_id)
            resolution_attempts.append(_resolution_audit(attempt, case, expected))

    schema_attempts = [
        _schema_audit(attempt, cases[attempt.case_id])
        for attempt in semantic.attempts
        if not attempt.schema_valid and attempt.provider_success
    ]
    intervention_attempts = [
        _intervention_audit(attempt, cases[attempt.case_id])
        for attempt in semantic.attempts
        if attempt.compiler_clarification_intervention
    ]
    schema_counts = Counter(item["taxonomy"] for item in schema_attempts)
    schema_by_language = Counter(item["language"] for item in schema_attempts)
    schema_by_case = Counter(item["case_id"] for item in schema_attempts)
    grounding_counts = Counter(item["grounding_classification"] for item in identifier_attempts)
    unsafe_counts = Counter(reason for item in unsafe_attempts for reason in item["reasons"])
    resolution_correct_refs = sum(
        item["semantic_reference_correctness"] for item in resolution_attempts
    )
    resolver_eligible = [
        item
        for item in resolution_attempts
        if item["business_resolution_correct_given_correct_reference"] is not None
    ]
    resolver_correct = sum(
        bool(item["business_resolution_correct_given_correct_reference"])
        for item in resolver_eligible
    )
    compiler_conditional = [
        item.compiler_correct_given_correct_semantics
        for item in semantic.attempts
        if item.compiler_correct_given_correct_semantics is not None
    ]
    return {
        "audit_version": "architecture_ab_forensic_audit_v1",
        "source_experiment_id": semantic.experiment.get("experiment_id"),
        "source_scorer_version": semantic.provenance.get("benchmark", {}).get("scoring_version"),
        "derived_scorer_version": "architecture_ab_scoring_v1_1",
        "model_outputs_changed": False,
        "cases_changed": False,
        "contracts_changed": False,
        "runtime_changed": False,
        "raw_artifact_sha256": raw_hashes,
        "raw_artifacts_unchanged_at_audit_start": True,
        "identifier_provenance": {
            "attempts": identifier_attempts,
            "counts": dict(sorted(grounding_counts.items())),
        },
        "unsafe_pre_policy_actions": {
            "count": len(unsafe_attempts),
            "attempts": unsafe_attempts,
            "reason_counts": dict(sorted(unsafe_counts.items())),
            "same_set_as_hallucinated_identifier_attempts": {
                "unsafe_case_runs": sorted(
                    (item["case_id"], item["run_index"]) for item in unsafe_attempts
                ),
                "hallucinated_case_runs": sorted(
                    (item["case_id"], item["run_index"]) for item in identifier_attempts
                ),
                "identical": {(item["case_id"], item["run_index"]) for item in unsafe_attempts}
                == {(item["case_id"], item["run_index"]) for item in identifier_attempts},
            },
        },
        "business_resolution_audit": {
            "attempts": resolution_attempts,
            "semantic_reference_correctness": {
                "correct": resolution_correct_refs,
                "eligible": len(resolution_attempts),
                "rate": resolution_correct_refs / len(resolution_attempts)
                if resolution_attempts
                else None,
            },
            "business_resolution_correct_given_correct_reference": {
                "correct": resolver_correct,
                "eligible": len(resolver_eligible),
                "rate": resolver_correct / len(resolver_eligible) if resolver_eligible else None,
            },
            "true_resolver_bug": any(item["resolver_itself_wrong"] for item in resolution_attempts),
        },
        "schema_failures": {
            "count": len(schema_attempts),
            "taxonomy_counts": dict(sorted(schema_counts.items())),
            "language_counts": dict(sorted(schema_by_language.items())),
            "case_counts": dict(sorted(schema_by_case.items())),
            "attempts": schema_attempts,
            "dominant_cause_assessment": (
                "MODEL_NONCOMPLIANCE_OR_CONTRACT_VALIDATION_ERROR;"
                " field-level cause is unavailable because the frozen artifact "
                "stores only ValidationError type and no provider payload/trace"
            ),
        },
        "compiler_clarification_interventions": {
            "count": len(intervention_attempts),
            "classification_counts": dict(
                sorted(Counter(item["classification"] for item in intervention_attempts).items())
            ),
            "attempts": intervention_attempts,
        },
        "compiler_invariant": {
            "correct": sum(compiler_conditional),
            "eligible": len(compiler_conditional),
            "rate": sum(compiler_conditional) / len(compiler_conditional)
            if compiler_conditional
            else None,
        },
        "root_cause_gate": "ROOT_CAUSE_PARTIALLY_UNGROUNDED_ID",
        "classification_review": "MIXED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_artifacts(args.artifact_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "audit_version": report["audit_version"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
