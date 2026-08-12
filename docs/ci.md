# CI/CD Quality Gates

The repository uses one blocking GitHub Actions workflow for pull requests and pushes to `main`.
It validates delivery artifacts but does not deploy them.

```text
Backend Quality ─┐
                 ├─> Security Checks -> Deterministic Evaluation -> Docker Build and Scan
Frontend Quality ┘                                              |
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
and contains no prompts, credentials, memory content, or raw business payloads. Audit persistence
is observational and does not authorize or replay business actions.

The integration bootstrap builds a complete versioned Qdrant snapshot and atomically activates the
logical knowledge alias before backend readiness. This keeps the deterministic hybrid lexical
vocabulary consistent with every stored sparse vector and makes stale-document removal a snapshot
property rather than an incremental delete operation.

### Docker Build and Scan

CI validates `docker compose config`, builds both application images, and scans each image for
unfixed-excluded critical vulnerabilities. No image is pushed by this workflow.

### Authenticated full-stack lifecycle smoke

Pull requests and pushes to `main` run `scripts/e2e_authenticated_smoke.py` after all other gates.
The script uses a per-run Compose project and fresh volumes, layers
`docker-compose.integration.yml`, and publishes services on Docker-assigned ports. It verifies:

- migrations, deterministic demo seed data, Qdrant ingestion, readiness, and frontend reachability;
- anonymous and invalid Bearer requests remain 401 while the demo support operator authenticates;
- an authenticated request through frontend/nginx creates a Risk-2 order cancellation proposal;
- the pending action is actor-, customer-, and conversation-bound and no early mutation occurs;
- a backend restart preserves the PostgreSQL checkpoint and confirmation resumes the real graph;
- the cancellation commits once, stores one idempotency receipt, and confirmation replay is safe;
- initial and resumed Operator Console projections expose bounded policy/tool metadata without the
  credential or hidden reasoning;
- the frontend-origin memory projection exposes seeded lifecycle metadata without persisted memory
  body text;
- strict msgpack restoration emits no permissive unregistered-type warnings.

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
```

Local Gitleaks, Trivy, and actionlint checks use the exact container versions declared in
`.github/workflows/ci.yml`.
