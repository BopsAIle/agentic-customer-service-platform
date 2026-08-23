# Deployment Lifecycle

The repository describes a production-oriented reference deployment, not a
managed deployment service. The release owner remains responsible for the
ingress, secret manager, rollout controller, database operations, and alert
routing.

## Before deployment

1. Validate the production Compose model and resource/security policy.
2. Run migrations against a disposable validation database and inspect the
   generated SQL/backfill plan.
3. Run `scripts/validate_production_config.py` in the deployment environment.
   It checks OIDC, durable persistence, semantic decision contract, evidence
   storage, debug mode, and secret placeholders without printing secret values.
4. Verify image digests, evidence manifests, backup metadata, and rollback
   artifacts.
5. Run backend/frontend quality checks and deterministic evaluation gates.

## Deployment

Use a rolling update behind an ingress or load balancer:

1. Start the new API replica with the same shared PostgreSQL, Qdrant, and
   evidence store.
2. Wait for `/health` and `/ready`; `/health` is process liveness while
   `/ready` includes required persistence/retrieval dependencies.
3. Inspect `/health/details` for bounded dependency status, latency summary,
   version, deployment identifier, and aggregate operational counters.
4. Shift traffic only after the new replica is ready and the smoke test passes.
5. Drain the old replica gracefully before termination.

Rollback when migrations fail, required readiness stays unavailable, evidence
hash verification fails, tenant isolation is not intact, or safety/evaluation
gates regress. Do not roll back by replaying unknown writes or by bypassing
confirmation/authentication controls.

## After deployment

- Run authenticated health/readiness and read-only operator smoke tests.
- Confirm migration and deployment identifiers in the operator diagnostics.
- Check latency, error, retry, circuit, grounding, and authentication alerts.
- Verify one controlled confirmation/idempotency path in an isolated test scope.
- Record the release source SHA and evidence manifest identities.

## Failure handling

Use the [runbooks](runbooks/) for database, provider, retrieval, idempotency,
and authentication incidents. Health diagnostics are bounded and are not a
substitute for logs/traces; investigation must continue with redacted,
privacy-safe operational evidence.
