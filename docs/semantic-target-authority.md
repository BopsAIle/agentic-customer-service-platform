# Semantic target authority

For `semantic_decision_v2`, semantic interpretation is not execution authority.

Concrete order and ticket identifiers must be deterministically grounded in the
trusted current user message before compilation. User-supplied identifiers still
go through normal existence and ownership validation.

Symbolic references such as `latest_order` remain available for authenticated,
read-only resolution. They are not authoritative targets for destructive
intents such as cancellation or refund. Those requests require clarification
unless they carry a grounded explicit identifier. This deliberately trades some
destructive-request convenience for a stronger mutation target boundary.
