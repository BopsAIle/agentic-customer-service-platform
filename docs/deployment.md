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

Both images receive configuration at runtime. No credentials, tokens, or environment files are
copied into either image.

## Health contract

| Endpoint | Meaning | Dependencies | Response body |
| --- | --- | --- | --- |
| `GET /health` | Process liveness | None | `{"status":"ok"}` |
| `GET /ready` | Traffic readiness | PostgreSQL, checkpoint backend, configured RAG backend | `{"status":"ready"}` or `{"status":"not_ready"}` |

Readiness failures return HTTP 503 without naming the failed dependency. Liveness deliberately
stays healthy during dependency outages so an orchestrator does not restart an otherwise healthy
process. The backend image healthcheck uses liveness; Compose uses readiness for service ordering.

## Graceful shutdown

The backend receives `SIGTERM` directly. Uvicorn stops accepting connections and is allowed up to
30 seconds to finish active requests. FastAPI lifespan then marks the process unready and closes:

1. the agent runtime and managed Qdrant client;
2. the LangGraph checkpoint provider and its connection pool;
3. the SQLAlchemy engine pool;
4. the owned OpenTelemetry tracer provider after a bounded flush.

Compose allows 35 seconds before forcefully stopping the backend. Lifecycle logs contain only
bounded component names and statuses; they do not contain prompts, customer data, or credentials.

## Local development stack

The base file keeps the simple local demo defaults:

```bash
docker compose up --build --detach
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:5173/
docker compose down
```

## Production-oriented Compose overlay

The overlay adds restart policies, read-only application filesystems, dropped Linux capabilities,
`no-new-privileges`, temporary writable filesystems, and configurable resource limits. Supply
credentials externally; do not put them in a committed `.env` file.

```bash
export POSTGRES_PASSWORD='set-outside-source-control'
export DATABASE_URL='postgresql+psycopg://app:encoded-password@db:5432/customer_service'
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build --detach
```

CPU and memory defaults can be overridden with `BACKEND_CPU_LIMIT`, `BACKEND_MEMORY_LIMIT`,
`FRONTEND_CPU_LIMIT`, `FRONTEND_MEMORY_LIMIT`, `POSTGRES_CPU_LIMIT`, `POSTGRES_MEMORY_LIMIT`,
`QDRANT_CPU_LIMIT`, `QDRANT_MEMORY_LIMIT`, `JAEGER_CPU_LIMIT`, and `JAEGER_MEMORY_LIMIT`.

For a real deployment, replace the local PostgreSQL and Qdrant services with managed or separately
operated dependencies as appropriate, supply identity and observability configuration through the
deployment environment, and terminate TLS at a trusted ingress or load balancer.
