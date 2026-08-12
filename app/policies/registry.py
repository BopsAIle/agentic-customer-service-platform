"""Compatibility export for the bounded non-production audit adapter."""

from app.policies.repository import InMemoryPolicyAuditLog

__all__ = ["InMemoryPolicyAuditLog"]
