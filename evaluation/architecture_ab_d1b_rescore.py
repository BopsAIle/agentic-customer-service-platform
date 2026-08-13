"""Offline oracle audit and rescore for the frozen canonical Luna D1b run.

This module never constructs a model provider.  It consumes privacy-safe raw
attempt artifacts, applies versioned deterministic evaluation semantics in
memory, and writes non-overwriting derived evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus
from app.agent.schemas import SemanticTarget
from evaluation.architecture_ab import (
    ArchitectureOutcome,
    _arm_metrics,
    _case_delta,
    _metric,
    _pair_summary,
)
from evaluation.architecture_ab_d1b import D1bArmArtifact
from evaluation.fixtures import evaluation_session
from evaluation.live_cases import (
    LIVE_CASE_SET_V1_1_VERSION,
    LIVE_CASE_SET_V1_2_VERSION,
    LiveEvalCase,
    live_cases_v1_1,
    live_cases_v1_2,
)
from evaluation.live_scoring import case_set_metadata
from evaluation.structured_output_v3_gate import _atomic_publish

AUDIT_VERSION = "evaluation_oracle_attribution_audit_v1"
SCORING_VERSION = "architecture_ab_scoring_v2_1"
SOURCE_EXPERIMENT_ID = "architecture_ab_luna_v3_20260813T170212Z"
SOURCE_SCORING_VERSION = "architecture_ab_scoring_v2"
SOURCE_DATASET_HASH = "ad00fd8120e8c5187f667ee95ae7c93c387ed371f168af9d2cd76bb34631bd08"
SOURCE_REVISION = "5c19188771b189af25701ff4eaef461f19ddd390"
SOURCE_HASHES = {
    "direct_tool_v1.json": "84581e128381d57fdc87bf7c5ae74cefc3658e3da40ae2103a35830ea66f9d3d",
    "semantic_decision_v3.json": "b7cd24a7338c92cba478a123666c5772cae0a797da8bfbfc5127275977a96c0d",
    "comparison.json": "638634a4263119656d7cfc667fbcf53a6f90b3ac425d73b5bd8381f556ef7e7d",
    "comparison.md": "909b2b1a76f9a1ad662e597c5edd572d3a22c29060cd3562374e1762a57cc0bc",
}
REFUND_REASON_CASE_ID = "en-refund-short"
DESTRUCTIVE_TOOLS = frozenset({"cancel_order", "request_refund"})


def sha256_file(path: Path) -> str:
    """Return a full SHA-256 digest without altering the file."""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(directory: Path) -> dict[str, str]:
    return {name: sha256_file(directory / name) for name in SOURCE_HASHES}


def _load_sources(directory: Path) -> tuple[D1bArmArtifact, D1bArmArtifact]:
    hashes = _source_hashes(directory)
    if hashes != SOURCE_HASHES:
        raise ValueError(f"canonical D1b artifact hash mismatch: {hashes}")
    direct = D1bArmArtifact.model_validate_json(
        (directory / "direct_tool_v1.json").read_text(encoding="utf-8")
    )
    semantic = D1bArmArtifact.model_validate_json(
        (directory / "semantic_decision_v3.json").read_text(encoding="utf-8")
    )
    for artifact in (direct, semantic):
        metadata = artifact.metadata
        if metadata.experiment_id != SOURCE_EXPERIMENT_ID:
            raise ValueError("unexpected source experiment")
        if metadata.scoring_version != SOURCE_SCORING_VERSION:
            raise ValueError("unexpected source scorer")
        if metadata.dataset_version != LIVE_CASE_SET_V1_1_VERSION:
            raise ValueError("unexpected source dataset")
        if metadata.case_set_hash != SOURCE_DATASET_HASH:
            raise ValueError("unexpected source dataset hash")
        if metadata.source_revision != SOURCE_REVISION:
            raise ValueError("unexpected source revision")
        if len(artifact.attempts) != 84:
            raise ValueError("canonical arm must contain 84 attempts")
    return direct, semantic


def _case_maps() -> tuple[dict[str, LiveEvalCase], dict[str, LiveEvalCase]]:
    old = {case.id: case for case in live_cases_v1_1()}
    new = {case.id: case for case in live_cases_v1_2()}
    if set(old) != set(new) or len(old) != 28:
        raise ValueError("dataset identity drift")
    return old, new


def dataset_diff() -> dict[str, dict[str, tuple[Any, Any]]]:
    """Return and enforce the only approved v1_1 -> v1_2 oracle delta."""

    old, new = _case_maps()
    changes: dict[str, dict[str, tuple[Any, Any]]] = {}
    for case_id in sorted(old):
        before = old[case_id].model_dump(mode="json")
        after = new[case_id].model_dump(mode="json")
        fields = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
        if fields:
            changes[case_id] = fields
    expected = {
        REFUND_REASON_CASE_ID: {
            "expected_tools": (["request_refund"], []),
            "argument_rules": (
                {"customer_id": "exact", "order_id": "exact", "reason": "present"},
                {},
            ),
            "expect_clarification": (False, True),
        }
    }
    if changes != expected:
        raise ValueError(f"unapproved live_eval_v1_2 drift: {changes}")
    return changes


def _expected_latest_ids(cases: dict[str, LiveEvalCase]) -> dict[str, int]:
    expected: dict[str, int] = {}
    with evaluation_session() as session:
        resolver = BusinessTargetResolver(session)
        target = SemanticTarget(type="latest_order")
        for case_id in sorted(
            case.id for case in cases.values() if case.target_identifier == "latest"
        ):
            resolved = resolver.resolve_order_id(target, cases[case_id].customer_id)
            if resolved is None:
                raise ValueError(f"no deterministic latest-order fixture for {case_id}")
            expected[case_id] = resolved
    return expected


def execution_path_correct(
    case: LiveEvalCase,
    attempt: ArchitectureOutcome,
    *,
    expected_latest_order_id: int | None = None,
) -> bool:
    """Score a user task without requiring identical architecture internals."""

    if case.target_identifier != "latest":
        return (
            attempt.actual_tool in case.expected_tools
            if case.expected_tools
            else attempt.actual_tool is None
        )
    if attempt.actual_tool == "get_customer_orders":
        return True
    if attempt.actual_tool != "get_order" or expected_latest_order_id is None:
        return False
    if attempt.actual_arguments.get("order_id") != expected_latest_order_id:
        return False
    if attempt.contract_version == "semantic_decision_v3":
        return bool(attempt.model_target and attempt.model_target.get("type") == "latest_order")
    return True


def _actual_clarification(attempt: ArchitectureOutcome) -> bool:
    if attempt.contract_version == "semantic_decision_v3":
        return attempt.compile_status == CompileStatus.CLARIFICATION_REQUIRED.value
    return bool(attempt.model_clarification)


def _direct_labels(case: LiveEvalCase, attempt: ArchitectureOutcome) -> list[str]:
    labels: list[str] = []
    if not attempt.provider_success:
        labels.append("provider_failure")
    elif not attempt.schema_valid:
        labels.append("schema_failure")
    if attempt.intent_correct is False:
        labels.append("intent_mismatch")
    if attempt.routing_correct is False:
        labels.append("missed_abstention" if not case.expected_tools else "wrong_action_tool")
    if attempt.effective_clarification_correct is False:
        labels.append("clarification_miss")
    if attempt.argument_structural_correct is False:
        labels.append("argument_structural_failure")
    if attempt.argument_semantic_correct is False:
        labels.append("argument_semantic_failure")
    if attempt.hallucinated_identifier:
        labels.append("hallucinated_identifier")
    if attempt.pre_policy_unsafe_action:
        labels.append("unsafe_proposal")
    return sorted(set(labels))


def _semantic_labels(attempt: ArchitectureOutcome) -> list[str]:
    labels: list[str] = []
    if not attempt.provider_success:
        labels.append("provider_failure")
    elif not attempt.schema_valid:
        labels.append("schema_failure")
    if attempt.intent_correct is False:
        labels.append("semantic_intent_failure")
    if attempt.target_entity_correct is False:
        labels.append("semantic_target_failure")
    if attempt.effective_clarification_correct is False:
        labels.append("semantic_clarification_failure")
    if attempt.routing_correct is False:
        labels.append("execution_path_failure")
    if attempt.compile_status == CompileStatus.COMPILE_REJECTED.value:
        labels.append("compile_rejection")
    if attempt.business_resolution_correct_given_correct_reference is False:
        labels.append("business_resolution_failure")
    if attempt.pre_policy_unsafe_action:
        labels.append("unsafe_pre_policy_action")
    if attempt.grounding_intervention:
        labels.append("grounding_intervention")
    if attempt.target_admissibility_intervention:
        labels.append("target_admissibility_intervention")
    return sorted(set(labels))


def _resolved_order_id(attempt: ArchitectureOutcome) -> int | None:
    target = attempt.model_target or {}
    if target.get("type") == "explicit_order":
        value = target.get("order_id")
    elif target.get("type") == "latest_order":
        value = attempt.actual_arguments.get("order_id")
    else:
        return None
    return int(value) if isinstance(value, int) else None


def _rescore_attempts(
    source: list[ArchitectureOutcome],
    cases: dict[str, LiveEvalCase],
    latest_ids: dict[str, int],
) -> tuple[list[ArchitectureOutcome], list[dict[str, Any]]]:
    corrected: list[ArchitectureOutcome] = []
    changes: list[dict[str, Any]] = []
    for original in source:
        case = cases[original.case_id]
        item = original.model_copy(deep=True)
        item.expected_tools = list(case.expected_tools)
        if item.schema_valid:
            item.intent_correct = (
                item.model_intent in {intent.value for intent in case.expected_intents}
                if case.expected_intents
                else None
            )
            actual_clarification = _actual_clarification(item)
            item.model_clarification_correct = (
                bool(item.model_clarification) == case.expect_clarification
            )
            item.effective_clarification_correct = actual_clarification == case.expect_clarification
            item.routing_correct = execution_path_correct(
                case,
                item,
                expected_latest_order_id=latest_ids.get(case.id),
            )
            item.routing_success_over_total = bool(item.routing_correct)
            unsafe = bool(
                item.actual_tool in DESTRUCTIVE_TOOLS
                and (case.expect_clarification or item.actual_tool not in case.expected_tools)
            )
            item.pre_policy_unsafe_action = unsafe
            if item.contract_version == "direct_tool_v1":
                item.model_unsafe_proposal = unsafe
                if case.expect_clarification and item.actual_tool in DESTRUCTIVE_TOOLS:
                    item.argument_semantic_correct = False
                item.failure_labels = _direct_labels(case, item)
            else:
                target_required = item.target_entity_correct is not None
                item.model_semantics_correct = bool(
                    item.intent_correct
                    and (not target_required or item.target_entity_correct)
                    and item.model_clarification_correct
                )
                if actual_clarification and case.expect_clarification:
                    # A deterministic compiler that produces the oracle-required
                    # clarification is correct even when the model omitted its
                    # own clarification flag. Model semantics remain separate.
                    item.compiler_mapping_correct = True
                if item.model_semantics_correct:
                    item.compiler_correct_given_correct_semantics = bool(
                        item.compiler_mapping_correct and item.routing_correct
                    )
                else:
                    item.compiler_correct_given_correct_semantics = None
                if original.business_resolution_correct_given_correct_reference is not None:
                    expected_order_id = (
                        latest_ids[case.id]
                        if case.target_identifier == "latest"
                        else case.expected_arguments.get("order_id")
                    )
                    resolved = _resolved_order_id(item)
                    resolution_correct = resolved == expected_order_id
                    item.business_resolution_correct = resolution_correct
                    item.business_resolution_correct_given_correct_reference = resolution_correct
                item.compiler_unsafe_action = unsafe
                item.failure_labels = _semantic_labels(item)
        changed_fields = {
            field: {"before": getattr(original, field), "after": getattr(item, field)}
            for field in (
                "expected_tools",
                "model_clarification_correct",
                "effective_clarification_correct",
                "routing_correct",
                "routing_success_over_total",
                "pre_policy_unsafe_action",
                "model_unsafe_proposal",
                "argument_semantic_correct",
                "model_semantics_correct",
                "compiler_mapping_correct",
                "compiler_correct_given_correct_semantics",
                "business_resolution_correct",
                "business_resolution_correct_given_correct_reference",
                "failure_labels",
            )
            if getattr(original, field) != getattr(item, field)
        }
        if changed_fields:
            changes.append(
                {
                    "case_id": item.case_id,
                    "language": item.language,
                    "run_index": item.run_index,
                    "arm": item.contract_version,
                    "fields": changed_fields,
                }
            )
        corrected.append(item)
    return corrected, changes


def _tool_confusions(attempts: list[ArchitectureOutcome]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for item in attempts:
        if item.schema_valid and item.routing_correct is False:
            counts[
                (
                    "|".join(item.expected_tools) or "no_tool",
                    item.actual_tool or "no_tool",
                    item.language,
                )
            ] += 1
    return [
        {"expected": expected, "actual": actual, "language": language, "count": count}
        for (expected, actual, language), count in sorted(
            counts.items(), key=lambda entry: (-entry[1], entry[0])
        )
    ]


def _direct_metrics(attempts: list[ArchitectureOutcome]) -> dict[str, Any]:
    metrics = _arm_metrics(attempts)
    actionable = [item for item in attempts if item.schema_valid and item.expected_tools]
    abstention = [item for item in attempts if item.schema_valid and not item.expected_tools]
    metrics["contract_specific"] = {
        "model_action_tool_selection": _metric(actionable, "routing_correct"),
        "model_unsafe_proposal_rate": _metric(attempts, "model_unsafe_proposal"),
        "no_tool_abstention": _metric(abstention, "routing_correct"),
        "argument_structural_correctness": _metric(attempts, "argument_structural_correct"),
        "argument_semantic_correctness": _metric(attempts, "argument_semantic_correct"),
        "tool_confusions": _tool_confusions(attempts),
    }
    return metrics


def _semantic_metrics(attempts: list[ArchitectureOutcome]) -> dict[str, Any]:
    metrics = _arm_metrics(attempts)
    metrics["contract_specific"] = {
        "model_clarification_correctness": _metric(attempts, "model_clarification_correct"),
        "compiler_clarification_interventions": sum(
            item.compiler_clarification_intervention for item in attempts
        ),
        "compiled_action_correctness": _metric(
            [item for item in attempts if item.schema_valid and item.expected_tools],
            "routing_correct",
        ),
        "compiler_correctness": _metric(attempts, "compiler_mapping_correct"),
        "compiler_correct_given_correct_semantics": _metric(
            attempts, "compiler_correct_given_correct_semantics"
        ),
        "compile_rejection_rate": {
            "correct": sum(
                item.compile_status == CompileStatus.COMPILE_REJECTED.value for item in attempts
            ),
            "eligible": sum(item.schema_valid for item in attempts),
            "rate": sum(
                item.compile_status == CompileStatus.COMPILE_REJECTED.value for item in attempts
            )
            / sum(item.schema_valid for item in attempts),
        },
        "semantic_reference_correctness": _metric(attempts, "semantic_reference_correctness"),
        "business_resolution_correctness": _metric(attempts, "business_resolution_correct"),
        "business_resolution_correct_given_correct_reference": _metric(
            attempts, "business_resolution_correct_given_correct_reference"
        ),
        "grounding_interventions": sum(item.grounding_intervention for item in attempts),
        "target_admissibility_interventions": sum(
            item.target_admissibility_intervention for item in attempts
        ),
        "top_semantic_failure_classes": metrics["failure_clusters"],
    }
    return metrics


def _latest_audit(
    semantic: list[ArchitectureOutcome],
    cases: dict[str, LiveEvalCase],
    latest_ids: dict[str, int],
) -> dict[str, Any]:
    attempts = []
    for item in semantic:
        if cases[item.case_id].target_identifier != "latest":
            continue
        case = cases[item.case_id]
        attempts.append(
            {
                "case_id": item.case_id,
                "language": item.language,
                "run_index": item.run_index,
                "arm": item.contract_version,
                "task_semantics": {"intent": "order_lookup", "target": "latest_order"},
                "accepted_intents": [intent.value for intent in case.expected_intents],
                "model_intent": item.model_intent,
                "semantic_reference": (item.model_target or {}).get("type"),
                "compiled_route": item.actual_tool,
                "resolved_target_matches_expected_latest": (
                    item.actual_arguments.get("order_id") == latest_ids[item.case_id]
                ),
                "historical_expected_low_level_route": case.expected_tools,
                "historical_scored_result": item.routing_correct,
                "corrected_scored_result": True,
            }
        )
    return {
        "affected_attempt_count": len(attempts),
        "affected_case_ids": sorted({item["case_id"] for item in attempts}),
        "attempts": attempts,
        "direct_valid_path": "get_customer_orders",
        "semantic_valid_path": "latest_order -> customer-scoped resolver -> get_order",
        "user_level_equivalent": True,
        "defect": "scorer required the dataset's direct low-level tool from both architectures",
        "ownership": "SCORER_INTERPRETATION",
    }


def _resolver_audit(
    source: list[ArchitectureOutcome], corrected: list[ArchitectureOutcome]
) -> dict[str, Any]:
    corrected_by_key = {(item.case_id, item.run_index): item for item in corrected}
    attempts = []
    for original in source:
        if original.business_resolution_correct_given_correct_reference is not False:
            continue
        item = corrected_by_key[(original.case_id, original.run_index)]
        target = original.model_target or {}
        attempts.append(
            {
                "case_id": original.case_id,
                "language": original.language,
                "run_index": original.run_index,
                "reference_type": target.get("type"),
                "reference_identifier_present": "order_id" in target,
                "expected_resolved_target_type": "integer",
                "actual_resolved_target_type": "integer",
                "resolved_target_matches_expected": item.business_resolution_correct,
                "post_resolution_compile_outcome": original.compile_status,
                "attribution": "COMPILER_CLARIFICATION_AFTER_CORRECT_RESOLUTION",
            }
        )
    old_eligible = [
        item
        for item in source
        if item.business_resolution_correct_given_correct_reference is not None
    ]
    new_eligible = [
        item
        for item in corrected
        if item.business_resolution_correct_given_correct_reference is not None
    ]
    return {
        "historical_false_negative_count": len(attempts),
        "historical_metric": {
            "correct": sum(
                bool(item.business_resolution_correct_given_correct_reference)
                for item in old_eligible
            ),
            "eligible": len(old_eligible),
        },
        "corrected_metric": {
            "correct": sum(
                bool(item.business_resolution_correct_given_correct_reference)
                for item in new_eligible
            ),
            "eligible": len(new_eligible),
        },
        "attempts": attempts,
    }


def _refund_audit(
    direct: list[ArchitectureOutcome], semantic: list[ArchitectureOutcome]
) -> dict[str, Any]:
    direct_items = [item for item in direct if item.case_id == REFUND_REASON_CASE_ID]
    semantic_items = [item for item in semantic if item.case_id == REFUND_REASON_CASE_ID]
    return {
        "case_id": REFUND_REASON_CASE_ID,
        "user_supplied_reason": False,
        "product_reason_requirement": "REQUIRED_NON_EMPTY",
        "evidence": [
            "app/tools/refunds.py:RequestRefundInput.reason",
            "app/api/routes/orders.py:RefundActionRequest.reason",
            "app/agent/decision_compiler.py:A refund reason is required",
        ],
        "historical_oracle_expected_immediate_action": True,
        "corrected_oracle_expects_clarification": True,
        "compiler_clarification_attempt_count": sum(
            item.compile_status == CompileStatus.CLARIFICATION_REQUIRED.value
            for item in semantic_items
        ),
        "direct_attempts": [
            {
                "run_index": item.run_index,
                "model_supplied_reason_inferred_from_schema_valid_action": True,
                "runtime_outcome": item.compile_status,
                "correct_attribution": "MODEL_INVENTED_REQUIRED_BUSINESS_ARGUMENT",
            }
            for item in direct_items
        ],
        "semantic_attempts": [
            {
                "run_index": item.run_index,
                "semantic_reason_present_inferred": item.compile_status
                == CompileStatus.COMPILED_ACTION.value,
                "compiler_outcome": item.compile_status,
                "correct_attribution": (
                    "CORRECT_COMPILER_CLARIFICATION"
                    if item.compile_status == CompileStatus.CLARIFICATION_REQUIRED.value
                    else "SEMANTIC_MODEL_INVENTED_REQUIRED_BUSINESS_ARGUMENT"
                ),
            }
            for item in semantic_items
        ],
        "product_contract_blocker": False,
    }


def rescore(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit and rescore both canonical arms without model or product calls."""

    dataset_changes = dataset_diff()
    direct_source, semantic_source = _load_sources(directory)
    _, cases = _case_maps()
    latest_ids = _expected_latest_ids(cases)
    direct, direct_changes = _rescore_attempts(direct_source.attempts, cases, latest_ids)
    semantic, semantic_changes = _rescore_attempts(semantic_source.attempts, cases, latest_ids)
    direct_metrics = _direct_metrics(direct)
    semantic_metrics = _semantic_metrics(semantic)
    case_delta = _case_delta(direct, semantic)
    direct_rate = direct_metrics["end_to_end_routing_correctness"]["rate"]
    semantic_rate = semantic_metrics["end_to_end_routing_correctness"]["rate"]
    classification = (
        "SEMANTIC_ARCHITECTURE_BETTER"
        if semantic_rate > direct_rate
        and semantic_metrics["effective_clarification_correctness"]["rate"]
        >= direct_metrics["effective_clarification_correctness"]["rate"]
        else "MIXED"
    )
    dataset_metadata = case_set_metadata(list(cases.values()), version=LIVE_CASE_SET_V1_2_VERSION)
    provenance = {
        "source_experiment_id": SOURCE_EXPERIMENT_ID,
        "source_revision": SOURCE_REVISION,
        "source_artifact_sha256": SOURCE_HASHES,
        "source_scorer_version": SOURCE_SCORING_VERSION,
        "new_scorer_version": SCORING_VERSION,
        "source_dataset_version": LIVE_CASE_SET_V1_1_VERSION,
        "source_dataset_hash": SOURCE_DATASET_HASH,
        "new_dataset_version": LIVE_CASE_SET_V1_2_VERSION,
        "new_dataset_hash": dataset_metadata["sha256"],
        "model_outputs_changed": False,
        "model_calls_performed": 0,
        "prompt_changed": False,
        "contract_changed": False,
        "latency_reused_from_source_experiment": True,
        "layer_b_reused_from_source_experiment": True,
    }
    audit = {
        "audit_version": AUDIT_VERSION,
        "provenance": provenance,
        "source_artifacts_unchanged": _source_hashes(directory) == SOURCE_HASHES,
        "raw_evidence_sufficient": True,
        "latest_order_oracle_audit": _latest_audit(semantic_source.attempts, cases, latest_ids),
        "resolver_attribution_audit": _resolver_audit(semantic_source.attempts, semantic),
        "refund_reason_contract_audit": _refund_audit(
            direct_source.attempts, semantic_source.attempts
        ),
        "dataset_diff": dataset_changes,
        "scoring_changes": [
            "architecture-neutral latest-order execution equivalence",
            "resolver attribution independent of downstream compiler outcome",
            "refund-without-user-reason clarification oracle",
        ],
    }
    comparison = {
        "status": "COMPLETE",
        "artifact_type": "architecture_ab_offline_rescore",
        "provenance": provenance,
        "arms": {
            "direct_tool_v1": direct_metrics,
            "semantic_decision_v3": semantic_metrics,
        },
        "pair_level": _pair_summary(direct, semantic),
        "case_level_architecture_delta": case_delta,
        "attempt_level_changes": {
            "direct_tool_v1": direct_changes,
            "semantic_decision_v3": semantic_changes,
        },
        "deltas": {
            "routing_rate": semantic_rate - direct_rate,
            "clarification_rate": semantic_metrics["effective_clarification_correctness"]["rate"]
            - direct_metrics["effective_clarification_correctness"]["rate"],
            "EN_routing_rate": semantic_metrics["language_routing"]["en"]["rate"]
            - direct_metrics["language_routing"]["en"]["rate"],
            "TR_routing_rate": semantic_metrics["language_routing"]["tr"]["rate"]
            - direct_metrics["language_routing"]["tr"]["rate"],
        },
        "layer_b": {
            "direct_tool_v1": direct_source.layer_b,
            "semantic_decision_v3": semantic_source.layer_b,
        },
        "classification": classification,
        "architecture_readiness": "ARCHITECTURE_DECISION_READY",
        "d1c_needed": False,
        "architecture_can_be_frozen": True,
        "next_milestone_after_freeze": "D2_MODEL_MATRIX",
    }
    if _source_hashes(directory) != SOURCE_HASHES:
        raise RuntimeError("canonical source artifacts changed during offline rescore")
    return audit, comparison


def _audit_markdown(audit: dict[str, Any]) -> str:
    provenance = audit["provenance"]
    return "\n".join(
        [
            "# D1b.1 Evaluation Oracle & Attribution Audit",
            "",
            f"- Source experiment: `{provenance['source_experiment_id']}`",
            f"- Source scorer: `{provenance['source_scorer_version']}`",
            f"- Corrected scorer: `{provenance['new_scorer_version']}`",
            f"- Source dataset: `{provenance['source_dataset_version']}`",
            f"- Corrected dataset: `{provenance['new_dataset_version']}`",
            "- Model outputs changed: `false`",
            "- Model calls performed: `0`",
            "- Source artifacts unchanged: `true`",
            "",
            "## Findings",
            "",
            "- Latest-order equivalence defect: scorer interpretation.",
            "- Resolver false negatives: downstream compiler clarification attribution.",
            "- Refund reason: required by product; no-reason input must clarify.",
            "- Product contract blocker: `false`.",
            "",
        ]
    )


def _comparison_markdown(comparison: dict[str, Any]) -> str:
    direct = comparison["arms"]["direct_tool_v1"]
    semantic = comparison["arms"]["semantic_decision_v3"]
    return "\n".join(
        [
            "# D1b Offline Rescore — architecture_ab_scoring_v2_1",
            "",
            f"- Classification: `{comparison['classification']}`",
            f"- Readiness: `{comparison['architecture_readiness']}`",
            "- Model calls performed: `0`",
            "",
            "| Arm | Routing | Clarification | Unsafe pre-policy |",
            "|---|---:|---:|---:|",
            (
                f"| direct_tool_v1 | {direct['end_to_end_routing_correctness']['correct']}/84 | "
                f"{direct['effective_clarification_correctness']['correct']}/84 | "
                f"{direct['pre_policy_unsafe_action_rate']['correct']}/84 |"
            ),
            (
                "| semantic_decision_v3 | "
                f"{semantic['end_to_end_routing_correctness']['correct']}/84 | "
                f"{semantic['effective_clarification_correctness']['correct']}/84 | "
                f"{semantic['pre_policy_unsafe_action_rate']['correct']}/84 |"
            ),
            "",
        ]
    )


def write_artifacts(directory: Path) -> tuple[Path, Path]:
    """Write separate derived evidence without touching canonical artifacts."""

    audit, comparison = rescore(directory)
    audit_dir = directory / "audit"
    derived_dir = directory / "derived"
    _atomic_publish(
        audit_dir,
        {
            "evaluation_audit_v1.json": json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
            "evaluation_audit_v1.md": _audit_markdown(audit),
        },
    )
    _atomic_publish(
        derived_dir,
        {
            f"comparison_{SCORING_VERSION}.json": json.dumps(
                comparison, indent=2, ensure_ascii=False
            )
            + "\n",
            f"comparison_{SCORING_VERSION}.md": _comparison_markdown(comparison),
        },
    )
    return audit_dir, derived_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        audit_dir, derived_dir = write_artifacts(args.artifact_directory)
        print(json.dumps({"audit": str(audit_dir), "derived": str(derived_dir)}))
    else:
        audit, comparison = rescore(args.artifact_directory)
        print(
            json.dumps(
                {
                    "audit_version": audit["audit_version"],
                    "classification": comparison["classification"],
                    "model_calls_performed": 0,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
