# Idempotency Incident Runbook

## Symptoms

- Duplicate-operation or receipt consistency alert.
- A write outcome is reported as unknown.

## Investigation

1. Stop replay attempts for the affected operation category.
2. Query the tenant-scoped receipt using the server-owned actor, tenant,
   operation, and idempotency key.
3. Compare the bounded request fingerprint and result identity; do not expose
   raw arguments or customer content in the incident record.
4. Check transaction commit errors and checkpoint state.

## Recovery

Treat an unknown write outcome as non-replayable until reconciliation proves
the result. If a receipt exists, return the recorded result; if it does not,
route to the approved reconciliation path. Never fix the incident by disabling
idempotency or confirmation.
