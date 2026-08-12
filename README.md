# Agentic Customer Service Platform

> A production-oriented reference platform for building safe, stateful, observable, and testable
> AI customer service systems.

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant-DC244C?logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![OpenTelemetry](https://img.shields.io/badge/Observability-OpenTelemetry-000000?logo=opentelemetry&logoColor=white)](https://opentelemetry.io/)
[![React](https://img.shields.io/badge/Operator_Console-React-61DAFB?logo=react&logoColor=black)](https://react.dev/)

This repository is an end-to-end agent platform, not only a conversational demo. It combines
authenticated HTTP boundaries, server-owned execution context, typed LangGraph orchestration,
deterministic policy enforcement, durable workflow state, customer-scoped memory and retrieval,
idempotent business writes, observability, and repeatable evaluation. The implementation focuses
on the control boundaries required when an LLM can interpret customer requests and propose real
business actions.

The project remains a reference implementation: local static bearer credentials keep development
simple, while replaceable identity, persistence, retrieval, and provider abstractions establish
production-oriented boundaries without claiming a complete deployment environment.

## Overview

Enterprise customer support agents need more than conversational fluency. They must authenticate
callers, preserve customer isolation, select tools, respect live business state, enforce safety
rules, recover from dependency failures, and expose enough telemetry for operators to understand
what happened.

This project provides those capabilities as separate, testable layers:

- ✓ LangGraph orchestration with typed state and structured decisions
- ✓ Authentication, role enforcement, and server-owned customer scope
- ✓ Actor-scoped PostgreSQL checkpoint persistence
- ✓ Hybrid RAG with citations
- ✓ Selective persistent customer memory
- ✓ Deterministic policy engine and confirmation boundaries
- ✓ Database-backed write idempotency and timeout-aware resilience
- ✓ Human escalation for high-risk work
- ✓ Offline evaluation framework with fault injection
- ✓ OpenTelemetry traces exported to Jaeger with bounded in-process metrics
- ✓ Reproducible CI gates and hardened non-root containers
- ✓ React Operator Console with metadata-only inspection

## Architecture

```mermaid
flowchart TD
    CLIENT[Customer / Support Operator] --> API[FastAPI HTTP Boundary]
    API --> AUTH[Authentication and RBAC]
    AUTH --> CONTEXT[Server-owned ExecutionContext]
    CONTEXT --> GRAPH[LangGraph Agent Runtime]

    GRAPH --> POLICY[Policy and Confirmation]
    GRAPH --> MEMORY[Customer-scoped Memory]
    GRAPH --> RAG[Configured RAG Runtime]
    GRAPH --> TOOLS[Typed Business Tools]

    POLICY --> TOOLS
    MEMORY --> POSTGRES[(PostgreSQL)]
    TOOLS --> POSTGRES
    GRAPH --> CHECKPOINTS[Durable Checkpoints]
    CHECKPOINTS --> POSTGRES
    RAG --> QDRANT[(Qdrant)]

    API -. safe metadata .-> OBS[OpenTelemetry / Jaeger]
    GRAPH -. safe metadata .-> OBS
    GRAPH -. deterministic scenarios .-> EVAL[Evaluation Harness]
    CONSOLE[React Operator Console] --> API
```

Authentication resolves a typed principal before protected HTTP work begins. The server derives an
`ExecutionContext` containing actor identity, effective customer scope, request ID, and conversation
ID; request bodies and model output cannot replace that identity. The LLM proposes a structured
decision, but customer, order, ticket, refund, cancellation, and escalation operations remain
behind typed tools, ownership checks, policy decisions, and confirmation rules.

PostgreSQL owns business records, idempotency receipts, persistent memory, and LangGraph
checkpoints. Qdrant provides the configured production retrieval path. OpenTelemetry and the
deterministic evaluation harness observe behavior without becoming authorization inputs.

## Production Hardening

The current implementation includes the following production-oriented controls:

| Area | Current boundary |
| --- | --- |
| Authentication and RBAC | Typed principals, replaceable authenticator protocol, static bearer development backend, protected business routes, operator-only APIs, and central customer-scope resolution |
| Durable checkpoints | Official PostgreSQL LangGraph checkpointer behind an application provider boundary; memory backend remains available for deterministic tests |
| Confirmation persistence | Pending actions survive process restarts and are bound to actor, actor type, customer scope, and conversation |
| Idempotent writes | Request-scoped keys and database uniqueness prevent duplicate refunds, cancellations, tickets, and escalations across workers |
| Timeout-aware resilience | Explicit LLM, retrieval, reranker, database, and HTTP timeouts; unknown write outcomes are not automatically replayed |
| Production RAG runtime | Configurable local or Qdrant retrieval, provider-neutral embeddings, optional reranking, citation preservation, and safe fallback metadata |
| CI/CD gates | Frozen backend and frontend installs, lint, types, tests, deterministic evaluations, vulnerability and secret scanning, image builds, Compose validation, and authenticated full-stack lifecycle smoke checks |
| Hardened containers | Multi-stage builds, non-root runtime users, graceful SIGTERM handling, bounded telemetry flush, readiness checks, security headers, and a production-oriented Compose overlay |

Together these controls make the repository a production-oriented deployment reference, but they
do not replace environment-specific identity providers, secret management, high-availability data
services, TLS termination, or infrastructure orchestration.

## Core Capabilities

### Agent Orchestration

The LangGraph state machine uses typed state, deterministic routing, and Pydantic-validated structured decisions. The graph separates understanding, tool selection, validation, policy evaluation, confirmation, retrieval, memory, execution, and response construction.

```text
load_context → retrieve_memory → check_pending_action
  ├─ confirmation → policy_revalidation → execute_confirmed_action → respond
  └─ new request → understand_request → select_tool → validate_tool
       → evaluate_policy → allow / confirm / human → execute / retrieve → respond
```

Short-term conversation state is durably checkpointed in PostgreSQL through the official
LangGraph checkpointer. Threads are scoped by actor type, actor ID, effective customer ID, and
conversation ID so caller-selected conversation identifiers cannot collide across principals.
Checkpoint reconstruction uses an explicit, exact-symbol allowlist for application-owned state;
unknown Python types cause checkpoint loading to fail. Pickle fallback is disabled. Local Compose,
integration, and production set `LANGGRAPH_STRICT_MSGPACK=true`, which also enables LangGraph's
schema-derived allowlist support. Existing msgpack checkpoints remain compatible because the
serialized format is unchanged and every intentional application state type is allowlisted.
`CHECKPOINT_BACKEND=memory` keeps tests and lightweight local runs deterministic. Tool inputs are
validated before use, and expected domain failures are mapped to bounded responses.

Policy decisions emit a durable operational audit trail to PostgreSQL when
`POLICY_AUDIT_BACKEND=postgres` (the production and integration requirement). Events contain only
bounded policy lifecycle metadata and are queried in deterministic, limited windows. Audit is
observational evidence: authentication, authorization, confirmation validity, business state,
and idempotency never consult it. The optional in-memory adapter is bounded and intended only for
tests/lightweight local runs. Database retention and pruning remain an operator responsibility;
this is not a compliance-grade immutable ledger.

The audit lifecycle covers every agent-originated mutating tool without persisting tool arguments
or business free text. Risk 1 records policy allow, execution attempt, and success/failure/unknown
outcome. Risk 2 records confirmation, revalidation, and the same execution outcomes. Risk 3 records
the human-required policy decision plus the actual escalation persistence outcome. Execution event
IDs are deterministic for a run/action/stage/outcome, so replayed observations do not create an
unbounded duplicate trail. Audit is persisted before a protected write is attempted; audit and the
business mutation are not one distributed transaction, so idempotency receipts remain authoritative
when post-commit audit evidence is unavailable.

Qdrant knowledge is deployed as immutable, versioned hybrid snapshots. The logical
`QDRANT_COLLECTION` name is an atomic alias (for example, `customer_service_knowledge`) pointing
to a physical `*_v_<snapshot-spec-prefix>` collection. `corpus_hash` identifies only the canonical
complete source corpus; `snapshot_id`/`snapshot_spec_hash` identifies the immutable index artifact
and includes embedding provider/model/dimension plus dense/sparse schema, knowledge-schema,
chunking, and lexical-index semantics. Therefore one corpus may safely have multiple snapshots
when its embedding or index specification changes. The full spec hash is retained in provenance;
the collection name uses only its first 16 hexadecimal characters.

`scripts.rag_ingest` builds the complete corpus, derives lexical vocabulary/IDF from that corpus,
validates dense+sparse schema and provenance, then switches the alias atomically. Incremental
mutation of the active hybrid collection is not supported because lexical semantics belong to the
complete snapshot. Use `python -m scripts.rag_ingest list` to inspect snapshot and corpus identities
and `python -m scripts.rag_ingest rollback <physical-collection>` for a controlled rollback; old
snapshots are retained until operators explicitly retire them. Readiness and activation validate
the full stored spec hash and runtime embedding compatibility. Legacy corpus-only snapshots without
spec provenance are incompatible and require a controlled rebuild; they are never silently reused.
Rollback across embedding-model versions also requires coordinated runtime embedding configuration.

Snapshot builds record a safe Qdrant `build_state` (`building`, `failed`, or `complete`) and the
expected point count in provenance. A retry can fully rebuild an exact, managed, inactive failed or
incomplete snapshot; complete compatible snapshots are validated and reused. Active snapshots are
never automatically repaired or deleted, and collections without matching managed provenance are
treated as collisions rather than deletion candidates. This is deterministic operator-triggered
rebuild/recovery, not background self-healing or automated snapshot pruning.

### Business Tools

The explicit tool registry currently includes:

- `get_customer`
- `get_customer_orders`
- `get_order`
- `get_customer_tickets`
- `get_ticket`
- `create_support_ticket`
- `cancel_order`
- `request_refund`
- `escalate_to_human`

Tools receive database sessions explicitly. The agent does not query persistence directly or bypass service-level ownership and state checks.

All business writes use actor-scoped idempotency receipts committed in the same database
transaction as the resulting mutation. Direct operator write APIs require an `Idempotency-Key`;
agent writes use their server-generated policy action ID. PostgreSQL also enforces one active
refund per order. If a commit response is lost, the operation is reported as outcome-unknown and
is never automatically replayed; retrying with the same key safely reconciles the stored receipt.

### Policy Engine

Risk is metadata on each registered tool and is evaluated outside the model:

| Risk | Handling | Examples |
| ---: | --- | --- |
| 0 | Automatic after validation | Customer, order, and ticket reads |
| 1 | Automatic after policy evaluation | Create a support ticket |
| 2 | Explicit confirmation required | Cancel an order, request a refund |
| 3 | Human handling path | Escalate a case |

The policy engine returns `allow`, `require_confirmation`, `require_human`, or `deny` with bounded reason codes. A policy evaluation failure denies the operation rather than guessing.

### Confirmation Workflow

Risk 2 proposals create a typed pending action with a stable `action_id`, validated arguments, customer and conversation ownership, and a default 300-second TTL.

- Confirmation is parsed deterministically.
- The exact stored action is confirmed; the model does not regenerate it.
- Ownership and live business state are revalidated immediately before execution.
- Expired, rejected, executed, failed, or substituted actions cannot run.
- Business operations enforce idempotency and duplicate-action rules.

### RAG

The agent depends on a provider-neutral knowledge retriever. `RAG_BACKEND=qdrant` is the production
default and queries the configured collection at runtime with independent dense and deterministic
lexical sparse branches fused by Qdrant's reciprocal-rank fusion, followed by optional reranking.
`RAG_BACKEND=local` loads the version-controlled Markdown corpus into a deterministic in-process
hybrid retriever with dense plus BM25-style lexical scoring for tests, offline evaluation, and
lightweight development. The storage-specific fusion implementations differ, but both paths
return the same ranked chunk schema and citation metadata.

Qdrant ingestion creates an unnamed dense vector plus a named `lexical` sparse vector and stores
the deterministic lexical vocabulary/weights as collection metadata. A dense-only or otherwise
incompatible existing collection is rejected; it is not deleted or silently upgraded. Re-run the
knowledge ingestion step into a fresh compatible collection (or explicitly replace the old
collection under operator control) when adopting this schema.

Embeddings are selected independently with `EMBEDDING_PROVIDER=deterministic|openai|huggingface`.
The OpenAI-compatible adapter uses the existing LangChain integration, while Hugging Face remains
an optional lazy adapter so the base installation does not pull a model runtime. Reranking can be
disabled with `RERANKER_ENABLED=false`; a reranker failure retains the original retrieval ranking
and is marked as degraded.

Answers expose citations derived only from retrieved `document_id#section` metadata. Retrieved content is evidence, not authority: it cannot select tools, authorize actions, or override business state. When retrieval is unavailable or insufficient, the agent declines to invent policy details.

### Persistent Memory

Selective memory is stored separately from short-term graph state and authoritative business records. Supported memory types are:

- `preference`
- `support_context`
- `explicit_instruction`
- `unresolved_issue`
- `interaction_summary`

Memory candidates pass through consent, confidence, sensitivity, conflict, expiry, and compaction rules. Retrieval is customer-scoped and bounded.

> Memory is contextual evidence, not authorization. It cannot select tools, confirm a Risk 2 action, bypass policy, or override current business state.

### Evaluation Framework

The deterministic offline harness executes versioned JSONL scenarios through the real graph with isolated SQLite state, a fake structured-decision provider, and scoped fault injection. It stores no chain-of-thought.

Current verified results:

| Suite | Scenarios | Result |
| --- | ---: | ---: |
| Full evaluation | 110 | 110/110 passed |
| Safety slice | 40 | 40/40 passed |
| Resilience slice | 28 | 28/28 passed |

| Metric | Result |
| --- | ---: |
| Intent accuracy | 100% |
| Tool selection accuracy | 100% |
| Confirmation compliance | 100% |
| Citation integrity | 100% |
| Memory retrieval accuracy | 100% |
| Memory write-policy compliance | 100% |
| Failure recovery accuracy | 100% |
| Unauthorized action rate | 0% |
| Duplicate write rate | 0% |

These are deterministic portfolio-scale evaluation results, not claims about live-model behavior or production traffic.
Runtime RAG evaluation hooks separately report retrieval success, citation availability, reranker
use, fallback behavior, and latency. They deliberately do not turn deterministic retrieval scores
into claims about live-model answer accuracy.

### Observability

OpenTelemetry captures bounded operational telemetry across:

- `agent.run` and meaningful graph nodes
- structured LLM decisions
- tool execution
- policy evaluation and revalidation
- confirmation handling
- RAG embedding, dense search, sparse search, fusion, reranking, and context construction
- memory retrieval, policy evaluation, persistence, deletion, and compaction
- resilience retry and recovery paths

Metrics cover request and tool latency, failures, retries, policy outcomes, confirmation results, RAG behavior, and escalations. High-cardinality customer data and free-form content are excluded from labels.

Compose exports OTLP over gRPC on port `4317` to the reproducibly pinned `jaegertracing/all-in-one:1.62.0` image. The Jaeger UI is exposed on port `16686`.

### Resilience

Failures are classified before the platform chooses a retry, degraded mode, or safe stop.

- Retryable reads use bounded retry and backoff.
- Writes are never blindly replayed.
- Unknown write outcomes are reported as ambiguous and require reconciliation.
- Reranker failure preserves fused dense and sparse results.
- RAG failure preserves valid business results but suppresses unsupported policy claims.
- Memory read failure continues without personalization; explicit memory writes fail visibly.
- Policy failure fails closed.

Runtime failures use a small source-aware taxonomy. `LLM_ERROR` is reserved for model/provider
interaction, `TOOL_ERROR` for controlled business-tool failures, `DEPENDENCY_ERROR` for external
service or infrastructure failures, and `INTERNAL_ERROR` for unexpected platform/runtime
failures. Existing validation, policy, retrieval, reranker, timeout, and domain categories remain
meaningful where they carry more specific semantics. `UNKNOWN_WRITE_OUTCOME` remains distinct
because a mutation may have committed. An error category describes failure source; it does not
decide retryability. The resilience coordinator and idempotency rules remain authoritative for
retry and reconciliation.

## Operator Console

The React control plane includes:

- **Playground** — send customer-scoped requests and inspect responses
- **Overview** — run metadata, intent, request type, risk, latency, and execution path
- **Tools** — selected and executed tools with risk and duration
- **Policy** — deterministic outcomes and bounded reason codes
- **RAG** — retrieved document metadata
- **Memory** — memory usage and customer-scoped lifecycle metadata
- **Trace** — ordered, safe execution events
- **Resilience** — dependency health, failures, retries, and degraded components

The console does **not** expose chain-of-thought, raw prompts, raw model responses, retrieved
document content, free-form tool arguments, customer names or emails, persisted memory body text,
or other sensitive payloads. The standard `/ui/memory/{customer_id}` response contains only memory
identity, type, normalized key, source, status, timestamps, and expiration metadata.
Memory content remains internal to the agent runtime under the existing customer scope and memory
policy. Removing the former operator-facing `content` field is an intentional privacy-hardening API
contract change.

Operator run projections are a durable PostgreSQL-backed read model in integration and production.
They survive backend restart and are visible across backend instances. Each row represents one graph
invocation: a confirmation request creates a new `run_id`, `request_id`, and trace while retaining
the same `conversation_id` and pending-action `action_id`. This keeps invocation duration and path
data historical; policy audit correlates the complete action lifecycle across runs by `action_id`.
They are bounded operator inspection data—not authorization, business state, checkpoint state,
idempotency state, or policy authority. Lightweight development and unit tests may use the bounded,
thread-safe memory adapter. List queries are capped at 100 rows and projection retention/pruning
remains an operator or database responsibility; policy audit remains the separate durable policy
evidence trail.

Identity semantics are explicit: `request_id` identifies one inbound HTTP request, `run_id` identifies
one graph invocation, and `trace_id` identifies that invocation's telemetry trace. `conversation_id`
is the stable application conversation/checkpoint grouping, while `action_id` is the opaque stable
correlation for one pending/destructive action across proposal, confirmation, revalidation, execution,
restart, and replay. The checkpoint `thread_id` is conversation/workflow continuity, not a run ID.

Consequently, an initial Risk-2 request and its confirmation produce separate run projections with
independent request/trace/path/duration data. Policy audit remains the cross-invocation lifecycle
evidence through `action_id`; it is not an authority source.

## Safety Model

The platform separates model reasoning from authority:

1. **The LLM proposes.** It produces a typed intent, request type, candidate tool, and validated
   arguments. Its output is untrusted input to the control plane.
2. **Deterministic systems authorize.** Authenticated identity, effective customer scope,
   ownership checks, live database state, and tool schemas decide whether a proposal is valid.
3. **Policy controls actions.** The policy engine assigns risk handling and returns a bounded
   `allow`, `require_confirmation`, `require_human`, or `deny` decision. Policy failures fail
   closed.
4. **Confirmation protects risky operations.** Refund and cancellation proposals bind a durable
   pending action to the actor, customer, and conversation. Confirmation revalidates ownership,
   expiry, policy, and current business state before an idempotent write executes.

Authorization precedence is explicit:

```text
Policy Engine
    > validated Business State
        > Current User Request
            > RAG Knowledge
                > Persistent Memory
```

Business state remains authoritative for ownership and valid transitions. Retrieved knowledge is
untrusted evidence and cannot authorize tools or change customer scope. Memory is non-authoritative
context and cannot confirm an action, bypass policy, or grant access.

Verified deterministic evaluation guarantees:

- ✓ Unauthorized action rate: **0%**
- ✓ Duplicate write rate: **0%**
- ✓ Confirmation compliance: **100%**

## Local Development

### Requirements

- Docker with Docker Compose
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm

### Start the complete local demo stack

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:5173>. The base Compose stack migrates PostgreSQL, loads deterministic demo
records, ingests the bundled knowledge into Qdrant, waits for backend readiness, and builds the
console with the same explicitly non-secret local demo credential used by the backend. The setup
step resets the demo business records each time it runs; it is not a production migration pattern.

`AUTH_MODE=local_demo` still authenticates every protected request through a real support-operator
`Principal`. `LOCAL_DEMO_AUTH_TOKEN=local-demo-support-token` is public localhost/demo
configuration, not a secret and not production IAM. Anonymous protected calls continue to return
401. `FRONTEND_AUTH_MODE=local_demo` selects the frontend's explicit in-memory demo provider; the
token is neither logged nor persisted to localStorage.

The default agent provider expects a real OpenAI-compatible LLM. For Compose, start an appropriate
model on the host (the defaults expect Ollama model `llama3.1` at port 11434), or set
`COMPOSE_LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` for your runtime. Without a reachable LLM,
health, readiness, authentication, operator reads, PostgreSQL, and Qdrant remain testable, but a
successful real-agent conversation is not available.

### Optional Ollama provider smoke

The local real-provider smoke uses the existing `OpenAICompatibleProvider`; Ollama is not a CI or
production dependency. Install and run the development baseline `qwen2.5:7b` in Ollama, then use:

```bash
LLM_PROVIDER=openai_compatible \
LLM_BASE_URL=http://localhost:11434/v1 \
LLM_MODEL=qwen2.5:7b \
LLM_API_KEY=ollama
```

The OpenAI-compatible provider also accepts the optional `LLM_REASONING_EFFORT` setting with
`none`, `low`, `medium`, or `high`. When unset, no reasoning override is sent and the provider's
default behavior is preserved. For example, a local model can be run with
`LLM_REASONING_EFFORT=none`; this is an opt-in provider setting, not a production recommendation.

For the Compose backend on macOS, set `COMPOSE_LLM_BASE_URL=http://host.docker.internal:11434/v1`.
The live smoke is opt-in and non-deterministic; `qwen2.5:7b` is a development baseline, not a
production recommendation. Deterministic integration mode remains the default for CI and the
canonical authenticated smoke.

### Deterministic authenticated integration smoke

CI and local integration verification do not depend on Ollama, OpenAI, API keys, or a developer
machine. Run the hermetic full-stack lifecycle smoke with:

```bash
make e2e-smoke
```

The script creates a unique Compose project with fresh PostgreSQL and Qdrant volumes and applies
`docker-compose.integration.yml`. That explicit override selects a narrowly scoped deterministic
decision provider under `APP_ENV=integration`; application configuration rejects that provider in
every other environment. The request still traverses nginx and FastAPI authentication, invokes the
real LangGraph, creates a Risk-2 cancellation proposal, persists it to PostgreSQL, restarts the
backend, resumes confirmation, executes one idempotent mutation, and verifies safe Operator Console
projections. The script always removes its isolated containers, network, and volumes unless
explicitly asked to leave a failed stack for CI diagnostics.

This smoke validates platform integration and deterministic control flow. It does not measure
real-model intent recognition, response quality, or semantic robustness; the optional local model
configuration above remains a separate development workflow.

For a dependency-free host-based RAG loop, set `RAG_BACKEND=local`; no Qdrant or external embedding
service is then required. Keep the embedding provider consistent between Qdrant ingestion and
runtime queries.

For a host-based backend development loop:

```bash
uv sync --frozen
make migrate
make seed
make dev
```

In another terminal, the Vite server reads the root `.env`, keeps the demo token in memory, and
proxies all backend API route families to `VITE_BACKEND_TARGET` (default
`http://localhost:8000`):

```bash
cd frontend
npm ci
npm run dev
```

Quick authentication checks:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --write-out '%{http_code}\n' http://127.0.0.1:8000/ui/system-health
curl --fail -H 'Authorization: Bearer local-demo-support-token' \
  http://127.0.0.1:8000/ui/system-health
```

The third command returns 401; the fourth authenticates as `operator-local-demo`.

### Local services

| Service | URL |
| --- | --- |
| Operator Console | http://localhost:5173 |
| FastAPI | http://localhost:8000 |
| Jaeger | http://localhost:16686 |
| Qdrant | http://localhost:6333 |
| PostgreSQL | `localhost:5432` |

Stop the Compose stack with `docker compose down` or `make down`.

## Deployment

Docker Compose is the supported local deployment workflow. The base `docker-compose.yml` starts
PostgreSQL, Qdrant, Jaeger, the backend, and the frontend with development-friendly defaults:

```bash
docker compose up --build --detach
docker compose down
```

`docker-compose.prod.yml` is a production-oriented Compose reference layered over the base file.
It adds external database credential requirements, restart policies, read-only application
filesystems, dropped capabilities, temporary writable filesystems, and configurable CPU and memory
limits:

```bash
export POSTGRES_PASSWORD='set-outside-source-control'
export DATABASE_URL='postgresql+psycopg://app:encoded-password@db:5432/customer_service'
export PRODUCTION_AUTH_TOKENS_JSON='{"replace-with-secret":{"actor_id":"operator","actor_type":"support_operator","roles":["support_operator"]}}'
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build --detach
```

The overlay is a deployment reference rather than a high-availability production orchestrator.
It forcibly disables the frontend demo credential and selects externally configured static bearer
authentication. Application startup rejects disabled or `local_demo` authentication when
`APP_ENV=production`, and rejects an empty static principal map. The static backend demonstrates
the replaceable `Authenticator` boundary; it is not a substitute for an environment-specific IAM
system or secret manager. The production frontend is built with `FRONTEND_AUTH_MODE=external_session`
and no browser credential. It remains fail-closed until a trusted external identity/session layer
supplies the `window.__OPERATOR_AUTH__` provider adapter; this repository does not ship OIDC, OAuth2,
BFF, gateway, or enterprise login code. Static bearer authentication remains a backend/service
adapter and is not browser IAM.
The production overlay runs migrations but does not seed demo records or ingest bundled knowledge;
operators must provision the configured Qdrant collection and ingest knowledge separately before
`/ready` can become healthy.
Kubernetes, Helm, cloud infrastructure, and automated deployment are future scope.

### Health and readiness

- `GET /health` is process liveness only and returns `{"status":"ok"}` while FastAPI can serve.
- `GET /ready` verifies PostgreSQL, checkpoint persistence, and the configured knowledge backend.
  It returns only `ready` or `not_ready`; dependency details are not exposed.
- Authenticated `GET /ui/system-health` projects the same request-scoped runtime health snapshot
  into safe component statuses for PostgreSQL, checkpoint persistence, retrieval, LLM configuration,
  and memory configuration. `healthy` means the boundary was actually checked; `not_probed` means
  LLM availability was not actively tested.

When `RAG_BACKEND=qdrant`, readiness additionally requires the configured collection to exist,
contain the repository's single unnamed dense vector plus the named `lexical` sparse vector,
use `Distance.COSINE`, match `EMBEDDING_DIMENSION`, contain valid lexical metadata, and contain at
least one indexed point from knowledge ingestion. Readiness observes this state and never creates
or changes a collection. `RAG_BACKEND=local` does not require Qdrant. Snapshot provenance also
validates the configured embedding identity and semantic index versions.

The health view does not make remote LLM calls. A configured LLM is reported as `not_probed`, not
healthy. Qdrant outage or incompatible active-snapshot provenance makes `/ready` return
`not_ready` and the authenticated health view report retrieval as `unavailable` or `incompatible`.
Health checks are observational and never build, activate, delete, or repair snapshots.

The backend and frontend images run as non-root users. For a production-oriented local Compose
model with read-only application filesystems, restart policies, and configurable CPU/memory
limits, layer `docker-compose.prod.yml` over the development file. It requires externally supplied
database credentials and does not provide secret management or deployment automation.

See [docs/deployment.md](docs/deployment.md) for probe semantics, graceful shutdown, external
configuration, resource limits, and container expectations.

## Testing

```bash
# Backend tests, lint, and types
make test
make lint
make typecheck

# Frontend tests, types, and production build
make frontend-test
make frontend-typecheck
make frontend-lint
make frontend-build

# Agent evaluation
make eval
make eval-safety
make eval-resilience
```

The default evaluation is offline and deterministic. Its CI gate fails on any unauthorized action, confirmation compliance below 100%, a failed critical safety scenario, task completion below 90%, or tool-selection accuracy below 90%.

## Continuous Integration

GitHub Actions runs ordered, blocking gates for backend quality, frontend quality, dependency and
secret scanning, deterministic evaluation, Docker/Compose validation, and image scanning. Pushes
to `main` additionally start the complete Compose stack and verify backend readiness
and frontend. Dependencies are installed only from `uv.lock` and `frontend/package-lock.json`.

Local equivalents:

```bash
make ci-backend
make ci-frontend
make eval && make eval-safety && make eval-resilience
make security-audit
make docker-validate
```

See [docs/ci.md](docs/ci.md) for the gate graph, scanner behavior, and authenticated lifecycle-smoke
details.

## Project Structure

```text
.
├── app/
│   ├── agent/              # LangGraph state, nodes, providers, and runtime
│   ├── api/                # FastAPI routes and transport boundaries
│   ├── auth/               # Principal, authenticator, RBAC, and scope boundaries
│   ├── core/               # Configuration, execution context, and database runtime
│   ├── memory/             # Selective persistent memory
│   ├── observability/      # OpenTelemetry traces, metrics, and middleware
│   ├── persistence/        # LangGraph checkpoint provider boundary
│   ├── policies/           # Risk policy, confirmation, and revalidation
│   ├── rag/                # Ingestion, retrieval, fusion, and generation
│   ├── resilience/         # Failure classification, retry, and fallback
│   ├── services/           # Business persistence operations
│   ├── tools/              # Typed agent-facing business tools
│   └── ui/                 # Safe operator projections
├── evaluation/
│   ├── datasets/           # 110 versioned scenarios
│   ├── metrics/            # Behavior and safety metrics
│   └── runner.py           # Isolated deterministic harness
├── frontend/               # React, TypeScript, Vite, and Tailwind console
├── tests/                  # Backend unit and integration tests
├── alembic/                # Database migrations
├── scripts/                # Seed and RAG ingestion commands
├── docker-compose.yml      # Local PostgreSQL, Qdrant, Jaeger, API, and frontend stack
├── docker-compose.integration.yml # Hermetic authenticated lifecycle smoke override
├── docker-compose.prod.yml # Production-oriented Compose policy overlay
└── Makefile                # Development and verification commands
```

## Roadmap

Completed:

- [x] Agent core
- [x] RAG
- [x] Evaluation framework
- [x] OpenTelemetry observability
- [x] Persistent memory
- [x] Resilience layer
- [x] Operator Console
- [x] Authentication, route authorization, and RBAC
- [x] Execution context propagation and customer isolation
- [x] Durable PostgreSQL agent checkpoints
- [x] Write idempotency and timeout enforcement
- [x] Production Qdrant RAG runtime separation
- [x] CI/CD quality and security gates
- [x] Hardened backend and frontend containers

Future:

- [ ] Voice agent
- [ ] Kubernetes deployment
- [ ] JWT/OIDC and enterprise identity-provider adapters
- [ ] Multi-agent workflows

## Engineering Decisions

### Why LangGraph?

Customer-support workflows are stateful and branch around retrieval, tools, confirmation, and recovery. An explicit graph makes those transitions inspectable, testable, and resumable without hiding control flow inside a prompt.

### Why deterministic policy?

Language models are useful for interpreting intent, not granting authority. Deterministic policy provides stable risk handling, reason codes, ownership enforcement, and a fail-closed boundary around real actions.

### Why isolate memory?

Personalization data has a different lifecycle and authority level from business records and conversation checkpoints. Isolation enables consent, TTL, conflict handling, deletion, and the invariant that remembered text cannot authorize work.

### Why evaluation-first?

Agent quality is behavioral. Versioned scenarios make confirmation, safety, retrieval, memory, escalation, and recovery measurable across complete multi-turn workflows rather than only individual functions.

### Why a resilience layer?

Provider, retrieval, database, and tool failures require different handling. Central classification makes retry and fallback behavior bounded, observable, and consistent—especially where repeating a write could create harm.

Dependency timeouts are enforced by the dependency client wherever native request deadlines are
available. LLM and embedding HTTP clients disable hidden SDK retries, Qdrant receives the effective
retrieval attempt timeout directly, and the application retry loop starts the next attempt only
after the previous call has returned. The platform does not use detached daemon threads to fake
cancellation. Local rerankers are allowed to finish; a provider-raised timeout or failure keeps
the original fused ranking. A business write whose commit outcome is unknown remains
`UnknownWriteOutcomeError` and is never automatically replayed.

### Optional live-model evaluation

The deterministic evaluation suites remain the CI quality and safety gates. An opt-in live
behavioral runner is available for measuring a real provider without making Ollama a CI
dependency:

```bash
ollama list
python -m evaluation.live --model qwen2.5:7b-instruct \
  --base-url http://localhost:11434/v1 --runs-per-case 3 --layer both
```

The runner uses the existing `OpenAICompatibleProvider`, freezes the current prompt for the
baseline, and writes JSON/Markdown reports under `artifacts/live-eval/` (ignored by Git). Layer A
scores model decisions without executing business mutations. Layer B runs a small isolated set of
real control-plane scenarios and reports unsafe proposals separately from unsafe execution and
confirmation bypass. Cases are versioned as `live_eval_v1`, and reports can be compared with:

```bash
python -m evaluation.live compare baseline.json candidate.json
```

The local `qwen2.5:7b-instruct` model is a development baseline, not a production recommendation.
Live results are non-deterministic and latency is machine-dependent; they do not change global LLM
health, which remains configured/not-probed unless an explicit health probe exists. Ollama is
optional and must be configured explicitly; it is never a silent fallback for deterministic or
hosted providers.
