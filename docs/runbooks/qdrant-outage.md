# Qdrant Outage Runbook

## Symptoms

- `/ready` reports the retrieval dependency unavailable or incompatible.
- RAG grounding status degrades or evidence is unavailable.

## Investigation

1. Check Qdrant readiness, active snapshot/alias, schema version, and storage.
2. Verify the evidence path is not using an incomplete or incompatible snapshot.
3. Confirm knowledge-only answers become bounded uncertainty and covered
   mutations cannot bypass grounding/target validation.

## Recovery

Restore the immutable compatible snapshot or fail over to the approved local
retrieval mode. Validate the snapshot before activation, then rerun readiness
and a read-only grounded-answer smoke test. Do not activate a mutable or
unverified collection.
