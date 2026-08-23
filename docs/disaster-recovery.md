# Disaster recovery

This document describes an operational recovery model for the production-oriented reference
topology. It is not a managed backup service or a certification of a particular provider's RPO/RTO.
Operators must replace the assumptions with values agreed for their environment.

## Recovery boundaries

| Data | Primary store | Recovery requirement |
| --- | --- | --- |
| Customer, order, policy, idempotency, audit, and run projections | PostgreSQL | Encrypted backups plus restore verification |
| Workflow checkpoints | PostgreSQL-backed LangGraph checkpoint store | Restore with the database and validate serializer compatibility |
| Knowledge snapshots | Qdrant | Snapshot/volume backup and embedding/schema identity verification |
| External evaluation evidence | Immutable object storage or release artifact | Manifest hash verification before use |
| Metrics, logs, and traces | Operational observability backend | Retain according to the observability policy; never treat telemetry as business state |

## Backup strategy

- Use encrypted, versioned PostgreSQL backups with point-in-time recovery where the deployment
  provider supports it.
- Back up Qdrant data or rebuild a complete compatible snapshot from the canonical knowledge
  corpus. A restored collection must match its embedding provider/model, dimension, schema,
  chunking, lexical-index, and snapshot provenance metadata before traffic is restored.
- Retain evidence manifests in Git or a release record. Store large payloads in immutable,
  access-controlled object storage and verify SHA-256 content hashes on restore.
- Keep backup credentials outside images, Compose files, and the repository.
- Test restoration on an isolated project at a documented cadence; a successful backup command is
  not evidence of a usable restore.

## Restore flow

```text
Declare incident
    -> isolate ingress and stop writes if required
    -> restore PostgreSQL to an isolated target
    -> validate migrations and checkpoint serializer compatibility
    -> restore or rebuild a verified Qdrant snapshot
    -> verify evidence manifests and object hashes
    -> run /health, /ready, and bounded lifecycle smoke checks
    -> switch ingress only after tenant, idempotency, and authority checks pass
```

Do not replay pending business effects from raw logs or projections. Idempotency receipts,
confirmed action state, and current business rows remain the authority for reconciliation.
Unknown write outcomes must be reconciled with the original idempotency identity rather than
automatically retried.

## RPO/RTO assumptions

The repository does not prescribe universal objectives. A deployment should record, at minimum:

- PostgreSQL RPO and RTO;
- Qdrant rebuild/restore RPO and RTO;
- evidence-store availability and retention window;
- maximum acceptable checkpoint loss; and
- the ingress cutover and rollback procedure.

For local Compose, volumes are single-node development state and are not a disaster-recovery
strategy. Multi-instance operation requires shared PostgreSQL/checkpoint state, shared evidence
storage, tenant-aware credentials, and an externally managed backup and ingress layer.

## Evidence recovery

Evidence is observational and must not be used as an authorization source. After restore, verify
the source SHA, artifact identity, schema version, and SHA-256 hash from each retained manifest.
If a payload is unavailable, mark it unavailable; do not silently regenerate it and present it as
the historical run.

For local evidence payloads, validate a restored manifest before use:

```bash
make recovery-validate MANIFEST=artifacts/evidence-manifests/<manifest>.json \
  ROOT=artifacts/evidence-payloads
```

The same hash and schema checks apply when a payload is restored from an
S3-compatible object store. Qdrant recovery assumes a versioned snapshot or a
rebuild from the canonical knowledge corpus; an unverified or incomplete
collection must not become the active grounding source.
