# Deterministic QA fixtures

The browser and authenticated smoke suites use isolated, deterministic data. They
must not share the developer database when validating a successful mutation and its
replay. The integration Compose override runs `scripts.reset_qa_fixtures` before
knowledge ingestion, so business state, durable projections, audit events,
idempotency receipts, checkpoints, and memory are reset together.

## Fixture orders

The seed data provides these stable QA cases:

| Order | Purpose | Expected state |
| --- | --- | --- |
| `1` | Refund candidate | Delivered, refund available, no existing refund |
| `2` | Invalid cancellation state | Shipped, cancellation unavailable |
| `3` | Duplicate-operation case | Existing refund operation is present |
| `9999` | Invalid order | No order exists for this identifier |

The scenario names used by release QA are:

| Fixture | Scope | Intended check |
| --- | --- | --- |
| `refund_success` | customer `1`, tenant `default`, order `1` | confirmation and one successful mutation |
| `invalid_cancellation` | customer `1`, tenant `default`, order `2` | business-state validation failure |
| `duplicate_refund` | customer `2`, tenant `default`, order `3` | duplicate-operation protection |
| `invalid_order` | customer `1`, tenant `default`, order `9999` | resource-not-found handling |
| `replay_after_success` | customer `1`, tenant `default`, order `1` | idempotent replay with no second effect |

## Isolated state contracts

| State | Clean starting condition | Scenario usage |
| --- | --- | --- |
| Customer scope | Customer `1` is the refund-success customer; customer `2` owns the duplicate fixture; customer `3` owns the metadata-only memory sentinel. | Keeps mutation, replay, and memory checks separate. |
| Refund lifecycle | Order `1` has no refund; order `3` has one processing refund; order `2` is shipped. | Fresh success, replay protection, and invalid cancellation. |
| Memory | All memory rows are cleared, then one bounded metadata-only sentinel is seeded for customer `3`. Customer `1` starts empty. | Memory-security runs use customer `1`; authenticated projection checks use customer `3`. |
| Knowledge | Local `app/knowledge` is ingested into the versioned `customer_service_knowledge` alias. | Grounded RAG uses the same corpus and snapshot contract on every reset. |

These records are presentation and test fixtures only. They do not grant authority;
the normal compiler, policy, confirmation, validation, and idempotency boundaries
remain in force.

## Reset procedure

Run operator journeys through:

```bash
scripts/run_operator_e2e.sh
```

The script uses the `customer-service-operator-e2e` Compose project by default,
starts the deterministic provider fixture, resets all QA state through the
integration override, and removes that project's volumes and orphans on exit.
Override `OPERATOR_E2E_PROJECT_NAME` when running suites in parallel.

The authenticated lifecycle smoke test uses its own process-scoped Compose project
(`customer-service-e2e-<pid>`) and also removes its volumes on exit. This gives the
refund-success and duplicate-replay checks a fresh database without changing
production runtime behavior or seed data.

To reset an already-running isolated integration project without touching the
developer database:

```bash
docker compose \
  --project-name customer-service-operator-e2e \
  --file docker-compose.yml \
  --file docker-compose.integration.yml \
  --env-file .env.example \
  run --rm --no-deps demo-setup python -m scripts.reset_qa_fixtures
```

Re-run knowledge ingestion after an in-place reset if the Qdrant volume was not
recreated:

```bash
docker compose --project-name customer-service-operator-e2e \
  --file docker-compose.yml --file docker-compose.integration.yml \
  --env-file .env.example run --rm --no-deps demo-setup python -m scripts.rag_ingest
```

Do not run the reset command against a production Compose project. If a run is
stopped before cleanup, remove only the named test Compose project before retrying;
do not reset unrelated application data.
