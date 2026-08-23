"""Backward-compatible import for the citation-constrained answer generator."""

from app.rag.answer_generator import GroundedAnswerGenerator, GroundingValidator

__all__ = ["GroundedAnswerGenerator", "GroundingValidator"]
