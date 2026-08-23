# Alerting Strategy

This alert model is a deployment reference for the control plane. It defines
bounded operational signals and response ownership; it is not a managed
monitoring service.

| Severity | Trigger | Owner | Response |
| --- | --- | --- | --- |
| Critical | PostgreSQL unavailable or checkpoint persistence fails | Data/runtime on-call | Stop writes, inspect database and checkpoint health, restore or fail over before reopening traffic. |
| Critical | Evidence store unavailable or manifest verification fails | Evidence/platform on-call | Keep evidence publication fail-closed, verify storage and hashes, then replay only approved recovery work. |
| Critical | Authentication provider outage or JWKS validation failures | Identity/platform on-call | Verify issuer, discovery, keys, clock skew, and provider status; do not bypass authentication. |
| Warning | Retry exhaustion increases above the workload baseline | Service owner | Inspect dependency category, deadlines, retry budget, and circuit state. Confirm no-write unknown outcomes remain unreplayed. |
| Warning | Circuit breaker opens | Dependency owner | Identify the bounded service identity, check dependency health, and wait for a controlled half-open recovery. |
| Warning | Request latency percentile increases | Service owner | Compare API, database, retrieval, checkpoint, and policy timing summaries; scale or tune the responsible boundary. |
| Warning | Clarification rate or RAG grounding rejection rate increases | Agent/retrieval owner | Review evidence availability and projection health; do not relax grounding or target validation. |
| Info | Deployment or migration completed | Release owner | Record version/deployment identity and complete smoke/readiness checks. |
| Info | Configuration change completed | Release owner | Confirm safe defaults, secret-manager source, and expected health transition. |

## Signal rules

- LLM/provider availability is a degradation signal, not a process readiness
  dependency. Recorded replay or safe uncertainty remains bounded by the
  configured execution path.
- Alerts must use aggregate counts, durations, dependency categories, and
  bounded statuses. Never attach prompts, tokens, customer identifiers,
  authorization headers, or raw provider payloads.
- Page only on sustained conditions with a deployment-aware window; one
  transient retry is not an incident by itself.

## Ownership boundaries

- Service/runtime owner: API lifecycle, checkpoint path, decision and execution
  error taxonomy.
- Data owner: PostgreSQL transactions, backups, migrations, and idempotency
  receipts.
- Retrieval owner: Qdrant snapshots, schema compatibility, and grounding
  availability.
- Identity owner: OIDC issuer, JWKS, clock, and principal mapping.
- Evidence owner: immutable manifests, object storage, hashes, and retention.
- Release owner: deployment lifecycle, rollback decision, and evaluation gates.
