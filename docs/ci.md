# CI/CD Quality Gates

The repository uses one blocking GitHub Actions workflow for pull requests and pushes to `main`.
It validates delivery artifacts but does not deploy them.

```text
Backend Quality ─┐
                 ├─> Security Checks -> Deterministic Evaluation -> Docker Build and Scan
Frontend Quality ┘                                              |
                                                                ├─> Operator Browser Journeys
                                                                └─> Authenticated Lifecycle Smoke
```

## Reproducible installation

- Python 3.12 dependencies are resolved in `uv.lock`. CI uses uv 0.11.16 and
  `uv sync --frozen`; a stale lockfile fails instead of being rewritten.
- Frontend dependencies are resolved in `frontend/package-lock.json` and installed with `npm ci`.
- The backend image installs production dependencies from `uv.lock` with `--frozen --no-dev`.
- The frontend image uses `npm ci` in a multi-stage build.
- Application build stages and Compose service images use versioned, digest-pinned base images.

Update dependency declarations and their lockfile together. Do not replace frozen installation
with an updating command in CI.

## Required gates

### Backend Quality

- Ruff lint and formatting check
- mypy across application, tests, evaluation, and scripts
- pytest

### Frontend Quality

- TypeScript typecheck
- ESLint
- Vitest
- Vite production build

### Security Checks

- `pip-audit` against the locked Python environment
- `npm audit --audit-level=high` against the frontend lockfile
- Gitleaks against repository history with findings redacted
- Trivy filesystem vulnerability, secret, and misconfiguration scan
- actionlint validation of workflow semantics

Scanners fail the job and do not upload reports. CI grants only read access to repository contents
and requires no secret or external credentials; the lifecycle smoke uses an explicitly public,
integration-only demo Bearer value.

### Deterministic Evaluation

The full, safety, and resilience datasets run independently of live LLM, Qdrant, or checkpoint
services by forcing the local RAG and in-memory checkpoint backends. These results measure the
deterministic harness and do not claim live-model accuracy.

Integration Compose also forces PostgreSQL policy audit storage. The authenticated lifecycle smoke
checks that policy evidence remains queryable after backend restart, is bounded and safely scoped,
and contains no prompts, credentials, memory content, or raw business payloads. The focused audit
matrix covers direct Risk-1 writes, confirmed Risk-2 writes, and Risk-3 escalation persistence,
including failure and unknown outcomes. Audit persistence is observational and does not authorize
or replay business actions; business idempotency remains the retry authority.

Runtime taxonomy tests also verify that genuine provider failures remain `LLM_ERROR`, controlled
tool failures use `TOOL_ERROR`, infrastructure failures use `DEPENDENCY_ERROR`, and unexpected
runtime failures use `INTERNAL_ERROR`, without exposing exception payloads. Unknown write outcomes,
timeouts, validation failures, and policy denials retain their existing safety semantics.

The integration bootstrap builds a complete versioned Qdrant snapshot and atomically activates the
logical knowledge alias before backend readiness. This keeps the deterministic hybrid lexical
vocabulary consistent with every stored sparse vector and makes stale-document removal a snapshot
property rather than an incremental delete operation.

Snapshot identity tests separately verify canonical `corpus_hash` and semantic `snapshot_id` values:
the same corpus/spec is idempotent, while model, dimension, schema, chunking, lexical-version, or
corpus changes produce distinct physical collections. Full spec provenance is required for
readiness, activation, and rollback; legacy corpus-only snapshots are rejected safely.

Recovery tests cover partial inactive builds, failed-state retry/rebuild, complete snapshot reuse,
active/unknown/full-hash collision protection, activation and rollback rejection for incomplete
artifacts, deterministic identity across rebuilds, and complete-corpus lexical reconstruction.

### Docker Build and Scan

CI validates `docker compose config`, builds both application images, and scans each image for
unfixed-excluded critical vulnerabilities. No image is pushed by this workflow.

### Operator browser journeys

Six serial Chromium journeys run against a fresh, isolated Compose project. A local deterministic
proposal fixture supplies typed semantic proposals without contacting an external provider; the
application's compiler, policy, confirmation, persistence, retrieval, projection, idempotency, and
execution paths remain unchanged. The suite verifies the refund confirmation boundary, prompt
injection containment evidence, duplicate replay safety, missing-target clarification, grounded
answer citations, and run investigation. It uploads bounded screenshots and Playwright failure
artifacts for 14 days and never uploads credentials, raw prompts, or hidden reasoning.

### Authenticated full-stack lifecycle smoke

Pull requests and pushes to `main` run `scripts/e2e_authenticated_smoke.py` after all other gates.
The script uses a per-run Compose project and fresh volumes, layers
`docker-compose.integration.yml`, and publishes services on Docker-assigned ports. It verifies:

- migrations, deterministic demo seed data, Qdrant ingestion, readiness, and frontend reachability;
- anonymous and invalid Bearer requests remain 401 while the demo support operator authenticates;
- an authenticated request through frontend/nginx creates a Risk-2 order cancellation proposal;
- the pending action is actor-, customer-, and conversation-bound and no early mutation occurs;
- a backend restart preserves the PostgreSQL checkpoint and durable PostgreSQL run projection;
  confirmation resumes the real graph with a new invocation run identity and the same action identity;
- the cancellation commits once, stores one idempotency receipt, and confirmation replay is safe;
- initial and resumed Operator Console projections remain separate invocation records, expose bounded
  policy/tool metadata, and correlate the action without the credential or hidden reasoning, including
  after restart;
- the frontend-origin memory projection exposes seeded lifecycle metadata without persisted memory
  body text;
- strict msgpack restoration emits no permissive unregistered-type warnings.

Frontend auth tests cover the explicit local-demo, integration, and external-session provider modes,
fail-closed production behavior without an auth source, 401/403 classification, in-memory-only
credential handling, and production bundle scans for demo/integration/static credential sentinels.

`LLM_PROVIDER=deterministic_integration` is available only with `APP_ENV=integration`. It supports
only this canonical seeded scenario and is rejected by configuration elsewhere. The production
Compose model excludes the integration override and CI checks the rendered model for leakage.

On failure, CI emits only bounded container logs with the demo credential redacted. Cleanup always
removes the CI-only containers, network, and volumes. Developer Compose volumes use a different
project namespace and are not affected.

This is an integration/control-plane proof, not a real-model quality evaluation. It validates
authentication, orchestration, policy confirmation, checkpoint durability, business execution,
idempotency, and safe projections. Live-model semantic quality remains outside this gate.

## Local verification

```bash
make ci-backend
make ci-frontend
make eval
make eval-safety
make eval-resilience
make security-audit
make docker-validate
make e2e-smoke
bash scripts/run_operator_e2e.sh
```

Local Gitleaks, Trivy, and actionlint checks use the exact container versions declared in
`.github/workflows/ci.yml`.
