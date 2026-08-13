"""Deterministic trust-boundary validation for semantic entity references."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.schemas import SemanticDecision

_DOMAIN_INTEGER_ID = re.compile(r"(?<![A-Za-z0-9_-])([1-9][0-9]*)(?![A-Za-z0-9_-])")


class GroundingStatus(StrEnum):
    GROUNDED = "grounded"
    SYMBOLIC = "symbolic"
    UNGROUNDED = "ungrounded"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"


class SemanticGrounding(BaseModel):
    """Privacy-safe, server-computed provenance result for a semantic target."""

    model_config = ConfigDict(extra="forbid")

    status: GroundingStatus
    reference_type: Literal["explicit_order", "explicit_ticket", "latest_order"] | None = None
    trusted_source: Literal["current_user_message"] | None = None


def _user_domain_ids(user_message: str) -> set[str]:
    """Return canonical integer IDs explicitly present in the current message."""

    return {str(int(value)) for value in _DOMAIN_INTEGER_ID.findall(user_message)}


def validate_semantic_grounding(decision: SemanticDecision, user_message: str) -> SemanticGrounding:
    """Validate semantic target provenance without using model claims or fuzzy matching."""

    target = decision.target
    if target is None:
        return SemanticGrounding(status=GroundingStatus.NOT_APPLICABLE)
    if target.type == "latest_order":
        return SemanticGrounding(
            status=GroundingStatus.SYMBOLIC,
            reference_type=target.type,
        )
    if target.type not in {"explicit_order", "explicit_ticket"}:
        return SemanticGrounding(status=GroundingStatus.INVALID)
    identifier = target.order_id if target.type == "explicit_order" else target.ticket_id
    if identifier is None:
        return SemanticGrounding(
            status=GroundingStatus.INVALID,
            reference_type=target.type,
        )
    status = (
        GroundingStatus.GROUNDED
        if str(identifier) in _user_domain_ids(user_message)
        else GroundingStatus.UNGROUNDED
    )
    return SemanticGrounding(
        status=status,
        reference_type=target.type,
        trusted_source="current_user_message" if status == GroundingStatus.GROUNDED else None,
    )
