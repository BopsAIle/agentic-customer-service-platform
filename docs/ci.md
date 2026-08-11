# CI/CD Quality Gates

The repository uses one blocking GitHub Actions workflow for pull requests and pushes to `main`.
It validates delivery artifacts but does not deploy them.

```text
Backend Quality ─┐
                 ├─> Security Checks -> Deterministic Evaluation -> Docker Build and Scan
Frontend Quality ┘                                              |
                                                                └─> Integration Smoke (main only)
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
and does not require application credentials.

### Deterministic Evaluation

The full, safety, and resilience datasets run independently of live LLM, Qdrant, or checkpoint
services by forcing the local RAG and in-memory checkpoint backends. These results measure the
deterministic harness and do not claim live-model accuracy.

### Docker Build and Scan

CI validates `docker compose config`, builds both application images, and scans each image for
unfixed-excluded critical vulnerabilities. No image is pushed by this workflow.

### Integration Smoke

After all other gates pass on `main`, Compose starts PostgreSQL, Qdrant, Jaeger, the backend, and
the frontend. CI waits for `/ready` and the frontend root page, then always removes containers and
volumes. Pull requests do not start the stack.

## Local verification

```bash
make ci-backend
make ci-frontend
make eval
make eval-safety
make eval-resilience
make security-audit
make docker-validate
docker compose up --build --detach
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:5173/
docker compose down --volumes --remove-orphans
```

Local Gitleaks, Trivy, and actionlint checks use the exact container versions declared in
`.github/workflows/ci.yml`.
