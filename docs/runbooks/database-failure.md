# Database Failure Runbook

## Symptoms

- `/ready` returns `not_ready`.
- `/health/details` reports `database` or `checkpoint` as a dependency failure.
- Retry exhaustion or transaction latency alerts increase.

## Investigation

1. Confirm the deployment identifier and failure window from health details.
2. Check PostgreSQL service health, connection pool saturation, storage, and
   transaction/lock pressure.
3. Check checkpoint readiness separately from application liveness.
4. Confirm no unknown-write outcome is being replayed.
5. Inspect redacted database and application error categories; never copy
   credentials, SQL parameters, prompts, or customer data into the incident.

## Recovery

Restore connectivity or fail over using the database provider procedure. Run
the migration/readiness checks, then an isolated read-only smoke test. Reopen
traffic only after `/ready` is healthy and idempotency receipts are readable.
