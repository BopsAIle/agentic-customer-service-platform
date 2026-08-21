"""Bounded, privacy-safe semantic attribution values.

These values describe already-computed semantic/compiler state.  They do not
participate in deciding whether an action may execute.
"""

from enum import StrEnum


class RefundReasonSupportStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MISSING = "MISSING"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_EVALUATED = "NOT_EVALUATED"


class CompilerClarificationCause(StrEnum):
    MISSING_REFUND_REASON = "MISSING_REFUND_REASON"
    UNSUPPORTED_REFUND_REASON = "UNSUPPORTED_REFUND_REASON"
    TARGET_REQUIRED = "TARGET_REQUIRED"
    CONTRADICTORY_ACTION = "CONTRADICTORY_ACTION"
    OTHER = "OTHER"
