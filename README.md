# Agentic Customer Service Platform

> A production-oriented agent control plane for reliable AI agents with policy enforcement, human approval boundaries, grounded retrieval, memory controls, and observable execution.

This repository demonstrates how to operate an AI agent without giving the
model direct authority over business effects. It combines stateful customer
conversations, workflow orchestration, deterministic decisioning, policy
controls, confirmation boundaries, controlled tools, RAG grounding, memory
isolation, and operator investigation views.

The core rule is:

> **The LLM proposes. Deterministic software decides what may execute.**

## Problem statement

LLMs are useful for interpreting requests and producing semantic suggestions,
but probabilistic output cannot safely own customer scope, target identity,
policy outcomes, or mutation authority. A production agent needs explicit
boundaries between model intelligence and system authority.

This platform keeps those responsibilities separate. Evidence is collected,
proposals are recorded as untrusted, deterministic controls decide admissibility,
and the runtime executes only through an approved path.

## Architecture

~~~mermaid
flowchart TB
    USER[User Request] --> GATEWAY[Gateway]
    GATEWAY --> CONTEXT[Context Assembly]
    CONTEXT --> SOURCES[Memory + RAG Retrieval]
    SOURCES --> ORCHESTRATOR[Agent Orchestrator]
    ORCHESTRATOR --> PROPOSAL[Action Proposal]
    PROPOSAL --> POLICY[Policy Engine]
    POLICY --> DECISION{Decision Compiler}
    DECISION -->|allow| EXEC[Tool Execution]
    DECISION -->|confirmation| CONFIRM[Human Confirmation Boundary]
    DECISION -->|human review| ESCALATE[Human Escalation]
    DECISION -->|deny| DENY[No Execution]
    CONFIRM --> EXEC
    ESCALATE --> EXEC
    EXEC --> OBS[Observability / Trace]
    DENY --> OBS
~~~

Layer responsibilities:

- **Gateway** accepts the request and establishes the request context.
- **Context Assembly** combines bounded customer state, memory, and retrieved
  knowledge. Context informs; it does not authorize.
- **Agent Orchestrator** preserves workflow state across missing information,
  confirmation, interruption, suspension, resume, and replacement.
- **Action Proposal** records semantic intent and a suggested action as
  untrusted model output.
- **Policy Engine and Decision Compiler** validate provenance, target
  admissibility, required fields, business state, risk, and policy.
- **Confirmation and escalation boundaries** require explicit human control for
  covered effects.
- **Tool Execution** is server-owned and is the only path that can commit an
  approved business effect.
- **Observability / Trace** projects bounded evidence, decisions, authority, and
  outcomes without exposing hidden reasoning, raw prompts, or model tokens.

## Key capabilities

- LangGraph-based workflow orchestration for stateful conversations.
- Security boundary detection before business intent routing.
- Policy-driven tool execution with deterministic target and business-state
  validation.
- Human-in-the-loop confirmation and escalation boundaries.
- RAG grounding with source, chunk, citation, and grounding metadata.
- Customer-scoped memory with explicit context-only authority.
- Persistence-backed idempotency and duplicate-effect protection.
- Workflow suspension, resume, replacement, and stale-state protection.
- Operator traces showing evidence, proposal, decision, authority, and outcome.
- OpenTelemetry-compatible operational projections and evaluation tooling.

## Demonstrated Scenarios

The screenshots below are deterministic showcase projections captured from the
existing console. They are presentation evidence, not live production
telemetry or certification.

### Human escalation

The agent recognizes a specialist request, applies the escalation policy, and
uses a bounded human-handoff action. The screenshot separates the
require_human decision, escalate_to_human action, completed handoff, and
controlled authority.

![Human escalation operator projection](docs/demo/human-escalation.png)

### Secure boundary enforcement

An instruction-override attempt is contained before it can become an
authorized workflow. The projection shows the deny decision, skipped model
execution, blocked-before-invocation reason, and no granted authority.

![Security boundary containing an instruction override](docs/demo/security-boundary.png)

### RAG grounding

The grounded response view places the customer exchange beside the retrieved
source, chunk, score, citation preview, and grounding status. Retrieved
evidence supports the response; it does not grant execution authority.

![RAG grounded response and evidence](docs/demo/rag-grounded-faq-conversation.png)

### Refund workflow

The refund scenario shows a structured proposal held at a confirmation
boundary. Evidence and deterministic validation can make a request eligible,
but no sensitive mutation proceeds without explicit approval.

![Refund workflow and confirmation boundary](docs/demo/refund-happy-path.png)

### Workflow recovery

An active workflow can be interrupted by an unrelated knowledge question,
suspended, answered through the RAG path, and resumed without losing bounded
pending-action context or bypassing confirmation.

![Workflow interruption and resume](docs/demo/workflow-interruption.png)

### Additional evidence views

The same evidence model is visible across memory, revalidation, and operator
investigation surfaces:

![Memory-aware conversation](docs/demo/memory-aware-conversation.png)

*A bounded memory item enriches context without becoming authorization.*

![Policy revalidation failure](docs/demo/policy-revalidation-failure.png)

*Business-state revalidation can prevent execution even after a proposal or confirmation step.*

![Operator observability timeline](docs/demo/operator-observability.png)

*The operational timeline connects gateway, context, memory, retrieval, policy, and tool ownership.*

![Operator investigation with decision and authority state](docs/demo/operator-investigation-full.png)

*The investigation header keeps evidence, decision, authority, and execution outcome distinct.*

See the [demo walkthrough](docs/demo/walkthrough.md) for scenario inputs,
expected boundaries, and observed projection behavior.

## Engineering Highlights

The project is designed for review by AI platform, MLOps, agent infrastructure,
and senior AI engineering teams:

- LangGraph-based workflow orchestration.
- Policy-driven tool execution.
- Human-in-the-loop approval boundaries.
- RAG grounding with evidence tracking.
- Memory isolation and lifecycle management.
- OpenTelemetry tracing and bounded operator projections.
- Deterministic evaluation and release-gate harnesses.
- Prompt-injection and instruction-override containment.
- Resilient workflow recovery and idempotent mutation protection.

## Evaluation results

The repository keeps separate release-gate summaries and bounded evaluation
slices. The current release evidence index reports:

| Area | Result |
| --- | --- |
| Deterministic evaluation | 110/110 |
| Safety evaluation | 40/40 |
| Resilience evaluation | 28/28 |
| M6.29B semantic and safety validation | 540/540 |
| Unsafe executable survivors | 0 |
| Unsafe executions | 0 |
| M6.34 operational release gate | D2D_RELEASE_GATE_PASS |

The latest bounded resilience/failure-recovery slice is recorded separately in
`evaluation/results/latest.json` and `evaluation/results/latest.md`: it contains
28 scenarios from run `eval-9fc295817532` at 100% pass rate. That slice is not a
replacement for the release-gate totals above, and the historical artifacts
remain available for reproducibility.

These results describe recorded evaluation artifacts and reference deployment
scope. They do not certify every model, workload, environment, or production
deployment.

Read the [evaluation overview](docs/evaluation-overview.md), [release evidence index](docs/release-evidence.md), and [D2d operational contract](docs/d2d-release-gate.md) for experiment identities, artifact paths, and acceptance criteria.

## Observability and operator workflow

The Runs & traces surface is a read-only investigation workflow:

~~~text
Request → Evidence → Proposal → Decision → Authority → Outcome
~~~

Operators can inspect request and workflow state, memory and RAG evidence,
action proposals, validation status, policy and confirmation outcomes,
authority and execution state, lifecycle timing, owners, trace identity, and
bounded reports.

The console intentionally omits chain-of-thought, raw provider responses,
secrets, unrestricted memory, prompts, and model token streams.

## Why this architecture exists

| Production problem | Architecture response |
| --- | --- |
| Hallucinated or unsupported claims | RAG grounding, provenance checks, citation metadata, and explicit uncertainty. |
| Unsafe agent execution | Security boundaries, target validation, Decision Compiler, Policy Engine, and confirmation gates. |
| Duplicate or stale business effects | Persistence-backed idempotency, revalidation, and controlled runtime execution. |
| Hard-to-debug agent behavior | Evidence projections, lifecycle timelines, bounded traces, and investigation reports. |

An agent should not own authority. The model proposes, the system decides, and
the runtime executes only approved effects.

## Technical stack

- **Backend:** Python, FastAPI, LangGraph-style agent workflow, PostgreSQL,
  Alembic, Qdrant, and typed business tools.
- **Frontend:** React, TypeScript, Vite, Tailwind, and Vitest.
- **Retrieval:** Hybrid dense/BM25 retrieval, fusion, reranking, and bounded
  citation-constrained answer generation.
- **Observability:** OpenTelemetry-compatible traces, bounded metrics, and a
  read-only operator console.
- **Verification:** Pytest, Ruff, Mypy, Playwright, deterministic evaluation,
  safety evaluation, and resilience evaluation.

## Local development

### Requirements

- Docker with Docker Compose
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js and npm

### Start the stack

~~~bash
cp .env.example .env
docker compose up --build --detach
~~~

Open <http://localhost:5173>. The local stack starts the backend, PostgreSQL,
Qdrant, Jaeger, and the Operator Console. Setup applies migrations, seeds
deterministic records, and loads the bundled knowledge base.

The offline evaluation gates do not require an external model provider. The
optional live proposal path uses a configured OpenAI-compatible provider for
semantic proposal generation only; grounding, compilation, policy,
confirmation, idempotency, and execution authority remain server-owned.

Useful endpoints:

| Service | URL |
| --- | --- |
| Operator Console | <http://localhost:5173> |
| FastAPI | <http://localhost:8000> |
| Jaeger | <http://localhost:16686> |
| Qdrant | <http://localhost:6333> |

Stop the stack with:

~~~bash
docker compose down
~~~

See [deployment](docs/deployment.md) for health, readiness, container, and
production-oriented topology details.

## Testing and CI

Backend quality gates:

~~~bash
make test
make lint
make typecheck
~~~

Frontend quality gates:

~~~bash
make frontend-test
make frontend-typecheck
make frontend-lint
make frontend-build
~~~

Offline evaluation gates:

~~~bash
make eval
make eval-safety
make eval-resilience
~~~

Browser-level operator journeys are available through the isolated Compose
workflow:

~~~bash
npm --prefix frontend ci
npx --prefix frontend playwright install chromium
bash scripts/run_operator_e2e.sh
~~~

The journeys cover grounded proposals, prompt-injection containment,
idempotent replay, clarification, RAG evidence, and run investigation without
requiring external provider credentials.

## Project structure

~~~text
app/                 FastAPI, agent graph, policy, persistence, RAG, tools, observability
frontend/            React, TypeScript, Vite, Tailwind Operator Console
tests/               Backend unit and integration tests
evaluation/          Deterministic evaluation and release-gate tooling
docs/                Architecture, deployment, evaluation, and showcase documentation
alembic/              Database migrations
scripts/              Seed, ingestion, validation, and integration helpers
docker-compose*.yml  Local, integration, and production-oriented Compose definitions
Makefile             Development and verification commands
~~~

## Limitations and scope

- This repository is a production-oriented reference implementation, not a
  managed production service or compliance certification.
- Model semantic errors can still occur; deterministic containment does not
  prove unseen failures are impossible.
- The Operator Console displays bounded projections and intentionally omits
  raw prompts, provider responses, secrets, unrestricted memory, and hidden
  reasoning.
- The release evidence covers the documented reference deployment. It does not
  certify public-internet TLS, enterprise IdP provisioning, multi-region
  operation, or unrestricted autoscaling capacity.
- Live provider configuration, browser login, external secret management, and
  deployment ownership remain environment-specific responsibilities.

## Further reading

- [Architecture](docs/architecture.md)
- [Identity and security boundaries](docs/security.md)
- [Distributed reliability boundaries](docs/reliability.md)
- [Memory privacy boundary](docs/memory-privacy.md)
- [Evaluation overview](docs/evaluation-overview.md)
- [Evaluation artifact retention policy](docs/evaluation-artifact-policy.md)
- [Release evidence](docs/release-evidence.md)
- [Deployment expectations](docs/deployment.md)
- [Production demo walkthrough](docs/demo/walkthrough.md)
- [Frontend design guidelines](docs/frontend-design-guidelines.md)
