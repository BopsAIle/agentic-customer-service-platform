"""Stable identities and scenario contracts for deterministic QA environments."""

QA_TENANT_ID = "default"

QA_CUSTOMER_IDS = {
    "refund_success": 1,
    "duplicate_refund": 2,
    "memory_metadata": 3,
}

QA_FIXTURE_ORDER_IDS = {
    "refund_candidate": 1,
    "shipped_order": 2,
    "duplicate_refund": 3,
}

QA_INVALID_ORDER_ID = 9999
QA_MEMORY_SENTINEL = "PRIVATE_MEMORY_SENTINEL_DO_NOT_EXPOSE"

QA_CONVERSATION_IDS = {
    "refund_success": "qa-refund-success",
    "refund_replay": "qa-refund-replay",
    "pending_confirmation": "qa-pending-confirmation",
    "memory_security": "qa-memory-security",
    "rag_grounding": "qa-rag-grounding",
}

QA_KNOWLEDGE_COLLECTION = "customer_service_knowledge"
