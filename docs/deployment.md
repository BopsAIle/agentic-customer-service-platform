# Production Container Expectations

The repository provides hardened backend and frontend images plus a production-oriented Compose
overlay. It does not provision infrastructure, manage secrets, publish images, or deploy services.

## Images

The backend uses a multi-stage build. uv resolves the production environment from `uv.lock` in the
builder, and only the virtual environment plus operational migration files are copied into the
runtime image. The runtime does not contain uv or frontend/build dependencies and runs as the
non-login `app` user (UID/GID 10001).

The frontend is built with `npm ci` and copied into an unprivileged nginx runtime on port 8080.
Hashed assets under `/assets/` are cached for one year as immutable. HTML uses revalidation, API
responses are not cached, unknown application paths fall back to `index.html`, and security headers
are applied to static and proxied responses.

Backend configuration is supplied at runtime. The local frontend build receives only the public,
non-secret demo token so the static console can exercise authenticated routes; the production
overlay explicitly builds without it. No real credentials or environment files are copied into
either image.

## Health contract

| Endpoint | Meaning | Dependencies | Response body |
| --- | --- | --- | --- |
| `GET /health` | Process liveness | None | `{"status":"ok"}` |
| `GET /ready` | Traffic readiness | PostgreSQL, checkpoint backend, configured RAG backend | `{"status":"ready"}` or `{"status":"not_ready"}` |

Readiness failures return HTTP 503 without naming the failed dependency. Liveness deliberately
stays healthy during dependency outages so an orchestrator does not restart an otherwise healthy
process. The backend image healthcheck uses liveness; Compose uses readiness for service ordering.

For `RAG_BACKEND=qdrant`, `/ready` is fail-closed until the configured collection exists and its
metadata matches the runtime contract: one unnamed dense vector, a named `lexical` sparse vector,
`Distance.COSINE`, and `EMBEDDING_DIMENSION`. The collection must also contain valid deterministic
lexical metadata and at least one indexed knowledge point; this is the selected
ingestion-completeness policy for the normal demo and production RAG path.
Readiness only observes Qdrant metadata and never creates, recreates, upserts, or deletes a
collection. `RAG_BACKEND=local` bypasses Qdrant readiness entirely. Matching dimensions are a
structural check only; without persisted model identity they do not prove that historical vectors
were produced by the currently configured embedding model. Production Qdrant retrieval fuses the
dense and lexical branches using reciprocal-rank fusion before optional reranking. Existing
dense-only collections must be re-ingested into a compatible hybrid collection; startup does not
delete or upgrade them automatically. Provision a new collection (or explicitly replace the old
one under an operator-controlled migration), set `QDRANT_COLLECTION`, and run
`python -m scripts.rag_ingest` before switching traffic.

## Graceful shutdown

The backend receives `SIGTERM` directly. Uvicorn stops accepting connections and is allowed up to
30 seconds to finish active requests. FastAPI lifespan then marks the process unready and closes:

1. the agent runtime and managed Qdrant client;
2. the LangGraph checkpoint provider and its connection pool;
3. the SQLAlchemy engine pool;
4. the owned OpenTelemetry tracer provider after a bounded flush.

Compose allows 35 seconds before forcefully stopping the backend. Lifecycle logs contain only
bounded component names and statuses; they do not contain prompts, customer data, or credentials.

## Timeout and retry coordination

Network dependencies use their native bounded request deadlines: the OpenAI-compatible model and
embedding clients receive explicit connect/read/write/pool timeouts with SDK retries disabled, and
Qdrant receives the effective retrieval-attempt timeout on each request. The retry coordinator
budgets the complete sequence and schedules an attempt only after the previous native call has
returned; it does not run synchronous I/O in a detached daemon thread. Local CPU rerankers are not
wrapped in a non-cancellable wall-clock thread, so a reranker failure or provider-native timeout
degrades to the original fused ranking. PostgreSQL uses pool acquisition, connection, and
statement timeouts, with transaction cleanup handled by the existing session boundary.

Write timeouts retain the unknown-outcome safety model. If a commit response cannot be confirmed,
the operation raises `UnknownWriteOutcomeError`, is not automatically replayed, and can only be
reconciled with the same idempotency key. These deadlines bound dependency work; they do not claim
to cancel arbitrary synchronous application code that has no native cancellation mechanism.

## Checkpoint deserialization boundary

PostgreSQL checkpoint data is integrity-sensitive. The application configures LangGraph's msgpack
serializer with a small allowlist of exact `(module_name, class_name)` application symbols and no
pickle fallback. Unknown Python types fail checkpoint loading rather than being imported or
reconstructed. Local Compose defaults `LANGGRAPH_STRICT_MSGPACK=true`; the integration and
production overlays set it unconditionally so LangGraph also derives allowed types from the graph
schema during compilation.

Checkpoints written before strict mode remain readable when they contain the same legitimate
application types because strict mode changes reconstruction authorization, not the msgpack wire
format. There is deliberately no permissive retry or automatic migration fallback. Deployments
with independently modified historical state should validate it before rollout. This boundary
reduces risk from tampered checkpoint rows; it does not protect a system whose application runtime
or database credentials are already fully compromised.

## Local development stack

The base file keeps an explicitly development-only authenticated demo. It migrates the database,
resets and loads demo records, ingests bundled knowledge into Qdrant, and starts the backend only
after setup succeeds:

```bash
cp .env.example .env
docker compose up --build --detach
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8000/ui/system-health)" = 401
curl --fail -H 'Authorization: Bearer local-demo-support-token' http://127.0.0.1:8000/ui/system-health
curl --fail http://127.0.0.1:5173/
docker compose down
```

`AUTH_MODE=local_demo` maps the configured non-secret demo token to a typed support-operator
principal. It does not make protected routes anonymous. The frontend holds that token in memory
and sends it through nginx, which explicitly preserves `Authorization` for `/agent` and `/ui`.

A real `/agent/chat` result additionally requires a reachable OpenAI-compatible LLM. The Compose
default uses `http://host.docker.internal:11434/v1`; change `COMPOSE_LLM_BASE_URL`, `LLM_MODEL`, and
`LLM_API_KEY` as needed. Do not report the agent path as validated if that runtime is absent.

For a hermetic integration proof instead of a live-model demo, run
`python3 scripts/e2e_authenticated_smoke.py`. It uses a separate Compose project and fresh volumes,
selects the explicit integration-only deterministic decision provider, and tears all isolated
resources down afterward. It validates the authenticated Risk-2 proposal, PostgreSQL-backed resume
after a backend restart, one idempotent business mutation, replay safety, and safe operator
projections. It does not validate real-model semantic quality.

## Production-oriented Compose overlay

The overlay adds restart policies, read-only application filesystems, dropped Linux capabilities,
`no-new-privileges`, temporary writable filesystems, and configurable resource limits. Supply
credentials externally; do not put them in a committed `.env` file.

```bash
export POSTGRES_PASSWORD='set-outside-source-control'
export DATABASE_URL='postgresql+psycopg://app:encoded-password@db:5432/customer_service'
export PRODUCTION_AUTH_TOKENS_JSON='{"replace-with-secret":{"actor_id":"operator","actor_type":"support_operator","roles":["support_operator"]}}'
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build --detach
```

CPU and memory defaults can be overridden with `BACKEND_CPU_LIMIT`, `BACKEND_MEMORY_LIMIT`,
`FRONTEND_CPU_LIMIT`, `FRONTEND_MEMORY_LIMIT`, `POSTGRES_CPU_LIMIT`, `POSTGRES_MEMORY_LIMIT`,
`QDRANT_CPU_LIMIT`, `QDRANT_MEMORY_LIMIT`, `JAEGER_CPU_LIMIT`, and `JAEGER_MEMORY_LIMIT`.

The production overlay sets `APP_ENV=production`, forces `AUTH_MODE=static`, requires a non-empty
externally supplied principal map, removes the demo token from backend/setup containers, and builds
the frontend without a bundled demo credential. It also forces `LANGGRAPH_STRICT_MSGPACK=true`.
It forces `POLICY_AUDIT_BACKEND=postgres`; production policy audit is a durable, bounded operational
evidence trail. Audit rows contain structured policy lifecycle metadata only and are never used as
an authorization or business-state source. Configure database retention/pruning operationally;
the application does not claim immutable compliance-ledger guarantees.
Backend startup rejects disabled or local-demo
authentication in production. Static opaque bearers are only the repository's current integration
adapter, not a claim of production IAM; deployers must provide secret rotation/storage and their
environment-specific identity integration.

For a real deployment, replace the local PostgreSQL and Qdrant services with managed or separately
operated dependencies as appropriate, supply identity and observability configuration through the
deployment environment, and terminate TLS at a trusted ingress or load balancer.
