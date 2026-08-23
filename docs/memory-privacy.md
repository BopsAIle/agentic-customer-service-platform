# Memory privacy boundary

Memory is not a database of everything the user says. It is governed state with an explicit
privacy policy, customer scope, retention behavior, and bounded operator projection.

## Classification

Every candidate is classified before persistence with:

- a sensitivity level: `PUBLIC`, `INTERNAL`, `SENSITIVE`, or `RESTRICTED`;
- a retention policy: standard, short-lived, or no-store;
- storage eligibility: allowed, redact, or reject; and
- redaction state.

The classifier detects typed categories including email, phone, payment identifiers, IBAN,
credit-card numbers, API tokens, passwords, secrets, national identifiers, and healthcare terms.
Detection metadata contains category names only. Detected values are never emitted to logs or
metrics.

## Write-time protection

The memory write boundary is:

```text
candidate → typed DLP classifier → allow | redact | reject
```

Normal customer preferences remain internal governed state. Email addresses and phone numbers are
redacted before storage and receive short retention. Payment identifiers, credentials, national
identifiers, healthcare-sensitive content, and similar restricted material are rejected and never
persisted. Existing instructional-content protections remain in place.

## Retrieval-time protection

Retrieval is filtered by:

- the server-resolved customer scope;
- the authenticated principal type and role; and
- the record sensitivity level.

Customer principals can retrieve only their own scoped memory. Support operators require the
support role. Restricted records are blocked even if a legacy or manually-created row exists.
The memory service does not grant authorization, override policy, satisfy confirmation, or create
execution authority.

## Retention

Standard retention follows the memory type’s existing TTL policy. Redacted sensitive memory uses
the short context TTL. A `no_store` candidate is rejected before persistence. Expired records are
filtered at retrieval and remain subject to the same scope and sensitivity checks.

The database stores only bounded privacy metadata alongside already-governed memory records. The
schema change is represented by an Alembic migration; historical rows receive conservative
internal/standard/not-required defaults during migration.

## Observability

The bounded metrics `memory_dlp_allowed`, `memory_dlp_redacted`,
`memory_dlp_rejected`, and `memory_sensitive_retrieval_blocked` expose policy outcomes and
category-independent levels/reasons only. They do not include memory text, detected values,
customer identifiers, PII, secrets, prompts, or provider data.

Memory enriches context only. It cannot authorize actions, bypass policy, or grant execution
authority.
