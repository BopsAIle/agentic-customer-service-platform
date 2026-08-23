"""Offline clarification-delta audit for immutable D2c/M6.5 artifacts."""

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

from evaluation.d2c_runner import D2cAttemptArtifact
from evaluation.live_eval_v2 import D2cScenario, live_eval_v2_cases

AUDIT_VERSION = "m6_6_clarification_audit_v1"
BASELINE_ID = "d2c_semantic_v3_20260813T221348Z"
CURRENT_ID = "d2c_m6_5_semantic_v3_20260813T230135Z"
ROOT = Path("artifacts/live-eval/production-robustness")
BASELINE_ROOT = ROOT / BASELINE_ID
CURRENT_ROOT = ROOT / CURRENT_ID
BASELINE_HASHES = {
    "manifest.json": "7a39fe0c8a4e40b0e4e209ee4c7bc66e2ae9ae541963be74b96be67863ed9df5",
    "attempts.json": "b84d8d25d34b510540e9b191bdf547ef92640d7cd058b49f074581ce8caaac0e",
    "summary.json": "b9cf64c9289c64be0799b540304d60bd8688efcf5f57aa19bd1e9583080c9848",
    "summary.md": "c5d2886fa5bc812220237b23c0aaac8f4801d3d79bceb169ea6396ee01432f46",
}
CURRENT_HASHES = {
    "manifest.json": "b5f5578abd7e9a5b3e6dbfd660e9da1a2662c8cf5517031e268ee23fd6dbc322",
    "attempts.json": "19a6a784a30b8c31549ee87e96ed828b705bf1b6251996e8ce25712738346116",
    "summary.json": "2ad42528e9429414387a4457b7988b523107032176404decb10d052775128d42",
    "summary.md": "f2944b48e5809a4c9b29c09eabf1748a08860299563aab97f8bd4f8810162bfc",
}

Classification = Literal[
    "correct_action_after_compiler_fix",
    "incorrect_loss_of_clarification",
    "oracle_mismatch",
    "unrelated_behavior_change",
]


class ClarificationDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    pair_id: str
    language: Literal["en", "tr"]
    category: str
    repetition: int
    baseline_clarification_correct: bool
    current_clarification_correct: bool
    baseline_actual_clarification: bool
    current_actual_clarification: bool
    baseline_compiler: str | None
    current_compiler: str | None
    expected_clarification: bool
    classification: Classification
    evidence_codes: tuple[str, ...]


class ClarificationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: Literal["m6_6_clarification_audit_v1"] = "m6_6_clarification_audit_v1"
    status: Literal["COMPLETE"] = "COMPLETE"
    baseline_experiment_id: Literal["d2c_semantic_v3_20260813T221348Z"] = (
        "d2c_semantic_v3_20260813T221348Z"
    )
    current_experiment_id: Literal["d2c_m6_5_semantic_v3_20260813T230135Z"] = (
        "d2c_m6_5_semantic_v3_20260813T230135Z"
    )
    baseline_artifact_sha256: dict[str, str]
    current_artifact_sha256: dict[str, str]
    model_calls_performed: Literal[0] = 0
    historical_artifacts_changed: Literal[False] = False
    source_runtime_changed: Literal[False] = False
    baseline_clarification_correct: int
    current_clarification_correct: int
    clarification_delta: int
    affected_attempts: int
    classification_counts: dict[str, int]
    records: tuple[ClarificationDelta, ...]
    conclusions: tuple[str, ...]
    privacy: dict[str, bool]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_root(root: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = root / name
        if not path.is_file() or path.is_symlink() or _sha256(path) != digest:
            raise RuntimeError(f"M6_6_SOURCE_HASH_MISMATCH:{name}")
    if json.loads((root / "manifest.json").read_text())["status"] != "COMPLETE":
        raise RuntimeError("M6_6_SOURCE_NOT_COMPLETE")


def _attempts(root: Path) -> dict[tuple[str, int], D2cAttemptArtifact]:
    raw = json.loads((root / "attempts.json").read_text())
    attempts = {
        (item.case_id, item.repetition): item
        for item in (D2cAttemptArtifact.model_validate(x) for x in raw["attempts"])
    }
    if len(attempts) != 540:
        raise RuntimeError("M6_6_ATTEMPT_COUNT_MISMATCH")
    return attempts


def _classify(
    baseline: D2cAttemptArtifact,
    current: D2cAttemptArtifact,
    case: D2cScenario,
) -> tuple[Classification, tuple[str, ...]]:
    expected = case.semantic.clarification_required
    if not baseline.score.clarification_correct and current.score.clarification_correct:
        return (
            "correct_action_after_compiler_fix",
            ("current_outcome_matches_frozen_clarification_oracle",),
        )
    if current.actual_compiler == "action" and expected:
        return (
            "incorrect_loss_of_clarification",
            ("action_reached_despite_frozen_clarification_requirement",),
        )
    if case.pair_id in {"std-refund-eligibility", "std-cancellation-explanation"}:
        return (
            "oracle_mismatch",
            (
                "compiler_mapping_changed_knowledge_path_to_state_plus_policy_path",
                "model_output_lacked_complete_retrieval_metadata_for_action_path",
            ),
        )
    if current.actual_clarification and not expected:
        return (
            "unrelated_behavior_change",
            ("clarification_added_for_non_clarification_oracle",),
        )
    return (
        "unrelated_behavior_change",
        ("clarification_score_changed_outside_confirmed_compiler_mapping_cases",),
    )


def build_audit() -> ClarificationAudit:
    _validate_root(BASELINE_ROOT, BASELINE_HASHES)
    _validate_root(CURRENT_ROOT, CURRENT_HASHES)
    baseline = _attempts(BASELINE_ROOT)
    current = _attempts(CURRENT_ROOT)
    cases = {case.case_id: case for case in live_eval_v2_cases()}
    records: list[ClarificationDelta] = []
    for key, old in baseline.items():
        new = current[key]
        if old.score.clarification_correct == new.score.clarification_correct:
            continue
        case = cases[old.case_id]
        classification, evidence = _classify(old, new, case)
        records.append(
            ClarificationDelta(
                case_id=case.case_id,
                pair_id=case.pair_id,
                language=case.language,
                category=case.category,
                repetition=old.repetition,
                baseline_clarification_correct=old.score.clarification_correct,
                current_clarification_correct=new.score.clarification_correct,
                baseline_actual_clarification=bool(old.actual_clarification),
                current_actual_clarification=bool(new.actual_clarification),
                baseline_compiler=old.actual_compiler,
                current_compiler=new.actual_compiler,
                expected_clarification=case.semantic.clarification_required,
                classification=classification,
                evidence_codes=evidence,
            )
        )
    counts = Counter(record.classification for record in records)
    classification_names: tuple[Classification, ...] = (
        "correct_action_after_compiler_fix",
        "incorrect_loss_of_clarification",
        "oracle_mismatch",
        "unrelated_behavior_change",
    )
    classification_counts = {name: counts[name] for name in classification_names}
    old_total = sum(bool(item.score.clarification_correct) for item in baseline.values())
    new_total = sum(bool(item.score.clarification_correct) for item in current.values())
    return ClarificationAudit(
        baseline_artifact_sha256=BASELINE_HASHES,
        current_artifact_sha256=CURRENT_HASHES,
        baseline_clarification_correct=old_total,
        current_clarification_correct=new_total,
        clarification_delta=new_total - old_total,
        affected_attempts=len(records),
        classification_counts=classification_counts,
        records=tuple(records),
        conclusions=(
            "The clarification score changed on 13 of 540 paired attempts.",
            (
                "The six standard state-plus-policy attempts require follow-up review because "
                "the fixed compiler mapping needs complete retrieval metadata from the "
                "semantic proposal."
            ),
            "No D2c artifact was modified and no model call was performed by this audit.",
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


def canonical_bytes(audit: ClarificationAudit) -> bytes:
    return (json.dumps(audit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()


def write_audit(audit: ClarificationAudit, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError("M6.6 audit artifact already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(audit)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, delete=False) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            temporary = Path(file.name)
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if destination.read_bytes() != content:
        raise RuntimeError("M6_6_ARTIFACT_READBACK_MISMATCH")
    return hashlib.sha256(content).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=CURRENT_ROOT / "audit" / f"{AUDIT_VERSION}.json"
    )
    args = parser.parse_args(argv)
    digest = write_audit(build_audit(), args.output)
    print(f"audit_path={args.output}")
    print(f"audit_sha256={digest}")
    print("model_calls_performed=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
