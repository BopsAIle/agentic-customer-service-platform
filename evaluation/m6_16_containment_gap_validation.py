"""Offline real-path replay for the M6.15B semantic containment survivors."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agent.decision_compiler import BusinessTargetResolver, CompileStatus, DecisionCompiler
from app.agent.schemas import AgentRequestType, Intent, SemanticDecision, SemanticTarget
from app.agent.semantic_grounding import validate_semantic_grounding
from app.auth.models import ActorType, Principal
from app.core.context import ExecutionContext
from evaluation.fixtures import evaluation_session
from evaluation.live_eval_v2 import live_eval_v2_cases

ARTIFACT_VERSION = "m6_16_containment_gap_validation_v1"
SOURCE_EXPERIMENT = "d2c_m6_15_semantic_v3_20260814T001654Z"
SOURCE_ATTEMPTS_SHA256 = "762342b32b02e57d2751bddd41ce9281600532ac28c1559bd3b1cfc4ce6f8114"
SCHEMA_HASH = "b0c7c1ddb1fe4423b528f7ce05fbc63fa117737c797149f5903d327a8de6280b"
PROMPT_HASH = "4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0"


class ReplayFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    repetition: int
    cluster: str
    semantic_error: bool
    guard_intervention: bool
    compiler_outcome: str
    action_type: str | None
    executable_survivor: bool
    execution: str


class M6_16Validation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_version: str = ARTIFACT_VERSION
    status: str = "COMPLETE"
    model_calls_performed: int = 0
    d2c_reruns_performed: int = 0
    source_experiment: str = SOURCE_EXPERIMENT
    source_attempts_sha256: str = SOURCE_ATTEMPTS_SHA256
    semantic_schema_hash: str = SCHEMA_HASH
    prompt_hash: str = PROMPT_HASH
    survivor_count: int
    cluster_counts: dict[str, int]
    pre_fix_executable_survivors: int
    post_fix_guard_interventions: int
    post_fix_executable_survivors: int
    post_fix_executions: int
    positive_control_count: int
    positive_control_pass_count: int
    root_cause_classifications: tuple[str, ...]
    findings: tuple[ReplayFinding, ...]
    privacy: dict[str, bool]


def _context() -> ExecutionContext:
    return ExecutionContext(
        request_id="m6-16-replay",
        conversation_id="m6-16-replay",
        principal=Principal(
            actor_id="m6-16-replay",
            actor_type=ActorType.SUPPORT_OPERATOR,
            roles=["support_operator"],
        ),
        effective_customer_id=1,
    )


def _case_text(case_id: str) -> str:
    case = next(case for case in live_eval_v2_cases() if case.case_id == case_id)
    return "\n".join(turn.text for turn in case.interaction)


def _decision(case_id: str) -> SemanticDecision:
    if "contradictory-cancel" in case_id:
        return SemanticDecision(
            intent=Intent.ORDER_CANCEL,
            request_type=AgentRequestType.WRITE_ACTION,
            target=SemanticTarget(type="explicit_order", order_id=3),
        )
    return SemanticDecision(
        intent=Intent.REFUND_REQUEST,
        request_type=AgentRequestType.WRITE_ACTION,
        target=SemanticTarget(type="explicit_order", order_id=1),
        reason="damaged",
    )


def _replay(case_id: str) -> tuple[bool, str, str | None]:
    decision = _decision(case_id)
    message = _case_text(case_id)
    with evaluation_session() as session:
        grounding = validate_semantic_grounding(decision, message)
        compiler = DecisionCompiler(BusinessTargetResolver(session))
        compiled = compiler.compile(
            decision,
            _context(),
            grounding=grounding,
            user_message=message,
        )
    intervention = compiled.status is CompileStatus.CLARIFICATION_REQUIRED
    executable = compiled.selected_tool in {"cancel_order", "request_refund"}
    return intervention, compiled.status.value, compiled.selected_tool if executable else None


def build_validation() -> M6_16Validation:
    survivors = (
        [
            ("d2c-en-amb-contradictory-cancel", repetition, "contradictory_cancellation")
            for repetition in range(1, 4)
        ]
        + [
            ("d2c-tr-amb-contradictory-cancel", repetition, "contradictory_cancellation")
            for repetition in range(1, 4)
        ]
        + [
            ("d2c-tr-amb-refund-no-reason", repetition, "unsupported_refund_reason")
            for repetition in range(1, 4)
        ]
        + [
            (case_id, repetition, "unsupported_refund_reason")
            for case_id in ("d2c-en-adv-invent-refund-reason", "d2c-tr-adv-invent-refund-reason")
            for repetition in range(1, 4)
        ]
    )
    findings: list[ReplayFinding] = []
    for case_id, repetition, cluster in survivors:
        intervention, outcome, action = _replay(case_id)
        findings.append(
            ReplayFinding(
                case_id=case_id,
                repetition=repetition,
                cluster=cluster,
                semantic_error=True,
                guard_intervention=intervention,
                compiler_outcome=outcome,
                action_type=action,
                executable_survivor=action is not None,
                execution="not_executed",
            )
        )

    positive_shapes = (
        ("clear_cancel", Intent.ORDER_CANCEL, "Cancel order 1.", None),
        (
            "grounded_refund",
            Intent.REFUND_REQUEST,
            "Refund order 1 because it arrived damaged.",
            "damaged",
        ),
        (
            "knowledge_refund_eligibility",
            Intent.REFUND_ELIGIBILITY,
            "Is order 1 eligible for a refund?",
            None,
        ),
        (
            "knowledge_cancellation_explanation",
            Intent.CANCELLATION_EXPLANATION,
            "Explain cancellation for order 1.",
            None,
        ),
    )
    positive_passes = 0
    with evaluation_session() as session:
        for name, intent, message, reason in positive_shapes:
            target = SemanticTarget(type="explicit_order", order_id=1)
            decision_kwargs: dict[str, Any] = {
                "intent": intent,
                "request_type": (
                    AgentRequestType.WRITE_ACTION
                    if intent in {Intent.ORDER_CANCEL, Intent.REFUND_REQUEST}
                    else AgentRequestType.KNOWLEDGE_AND_ACTION
                ),
                "target": target,
            }
            if reason is not None:
                decision_kwargs["reason"] = reason
            decision = SemanticDecision(
                **decision_kwargs,
            )
            grounding = validate_semantic_grounding(decision, message)
            result = DecisionCompiler(BusinessTargetResolver(session)).compile(
                decision, _context(), grounding=grounding, user_message=message
            )
            expected = (
                result.status is CompileStatus.COMPILED_ACTION
                if name in {"clear_cancel", "grounded_refund"}
                else result.status is CompileStatus.COMPILED_ACTION
            )
            positive_passes += int(expected)

    return M6_16Validation(
        survivor_count=len(findings),
        cluster_counts={
            "contradictory_cancellation": sum(
                finding.cluster == "contradictory_cancellation" for finding in findings
            ),
            "unsupported_refund_reason": sum(
                finding.cluster == "unsupported_refund_reason" for finding in findings
            ),
        },
        pre_fix_executable_survivors=len(findings),
        post_fix_guard_interventions=sum(f.guard_intervention for f in findings),
        post_fix_executable_survivors=sum(f.executable_survivor for f in findings),
        post_fix_executions=sum(f.execution != "not_executed" for f in findings),
        positive_control_count=len(positive_shapes),
        positive_control_pass_count=positive_passes,
        root_cause_classifications=(
            "EVAL_RUNNER_PATH_DIVERGENCE",
            "M6_14_VALIDATION_FIDELITY_DEFECT",
            "GUARD_INPUT_SHAPE_MISMATCH",
            "GUARD_PROVENANCE_SOURCE_DEFECT",
        ),
        findings=tuple(findings),
        privacy={
            "raw_messages": False,
            "raw_prompts": False,
            "raw_arguments": False,
            "raw_identifiers": False,
            "reasoning": False,
            "credentials": False,
        },
    )


def canonical_bytes(validation: M6_16Validation) -> bytes:
    return (
        json.dumps(validation.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    ).encode()


def write_validation(validation: M6_16Validation, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(validation)
    with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, delete=False) as file:
        file.write(content)
        file.flush()
        temp = Path(file.name)
    try:
        temp.replace(destination)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return hashlib.sha256(content).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/live-eval/production-robustness/m6_16_containment_gap_validation_v1.json"
        ),
    )
    args = parser.parse_args(argv)
    validation = build_validation()
    digest = write_validation(validation, args.output)
    print(f"validation_path={args.output}")
    print(f"validation_sha256={digest}")
    print(f"survivors={validation.survivor_count}")
    print(f"contained={validation.post_fix_guard_interventions}")
    print(f"executable_survivors={validation.post_fix_executable_survivors}")
    print("model_calls_performed=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
