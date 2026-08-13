"""Deterministic authority boundary before semantic target resolution."""

from __future__ import annotations

from enum import StrEnum

from app.agent.schemas import Intent, SemanticTarget
from app.agent.semantic_grounding import GroundingStatus, SemanticGrounding


class TargetAdmissibility(StrEnum):
    ADMISSIBLE = "admissible"
    ADMISSIBLE_SYMBOLIC_READ = "admissible_symbolic_read"
    REQUIRES_CLARIFICATION = "requires_clarification"
    INVALID = "invalid"


DESTRUCTIVE_TARGET_INTENTS = frozenset({Intent.ORDER_CANCEL, Intent.REFUND_REQUEST})


def assess_target_admissibility(
    intent: Intent,
    target: SemanticTarget | None,
    grounding: SemanticGrounding | None,
) -> TargetAdmissibility:
    """Decide whether a semantic target may reach deterministic compilation.

    A model-proposed symbolic target is never authoritative for a destructive
    intent.  Symbolic references remain available to bounded read paths.
    """

    if target is None:
        return (
            TargetAdmissibility.REQUIRES_CLARIFICATION
            if intent in DESTRUCTIVE_TARGET_INTENTS
            else TargetAdmissibility.ADMISSIBLE
        )
    if target.type == "latest_order":
        if intent in DESTRUCTIVE_TARGET_INTENTS:
            return TargetAdmissibility.REQUIRES_CLARIFICATION
        return TargetAdmissibility.ADMISSIBLE_SYMBOLIC_READ
    if target.type not in {"explicit_order", "explicit_ticket"}:
        return TargetAdmissibility.INVALID
    if grounding is not None and grounding.status in {
        GroundingStatus.UNGROUNDED,
        GroundingStatus.INVALID,
    }:
        return TargetAdmissibility.REQUIRES_CLARIFICATION
    return TargetAdmissibility.ADMISSIBLE
