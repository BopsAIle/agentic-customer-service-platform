# Agentic Customer Service Platform

> Production-oriented agent control plane and evidence-driven agent reliability platform for safe AI execution.

This project shows how a customer-service agent can use model proposals while
keeping decisions, policy, confirmation, and runtime effects under deterministic
system control.

The central design rule is simple:

> **The LLM proposes. Deterministic software decides what may execute.**

The model can misunderstand a request or produce an unsupported argument. That output remains a proposal until server-owned grounding, target validation, compilation, policy, confirmation, and idempotency checks allow an action to proceed.

## Problem

LLMs are probabilistic. A production agent also needs deterministic authority:
it must know which customer and target are in scope, which evidence supports a
request, whether policy allows it, and whether a sensitive change has been
confirmed.

The platform keeps those questions separate from response generation. The
model suggests meaning and actions; server-owned controls decide what may
proceed.

## Design principle

An agent should not own authority.

The model proposes.
The system decides.
The runtime executes only approved effects.

This is a production-oriented agent control plane built around bounded
authority, deterministic decisioning, evidence-backed operations, and safety
governance for LLM systems.

## What to see first

The React Operator Console is designed as a compact AI platform control plane:

1. **Overview** explains the architecture and release evidence.
2. **Agent Playground** lets an engineer submit a business or safety scenario through the existing API.
3. **Investigation** shows the bounded trace, grounding evidence, policy result, and execution state.
4. **Safety** shows the deterministic evaluation and operational release-gate evidence.

No screen exposes chain-of-thought, raw provider responses, secrets, or direct production mutation controls.

## Unified Agent Experience

The `/chat` view brings the customer interaction and the operator's bounded
agent observability into one screen. It reuses the existing `/agent/chat`
workflow, so the conversation remains connected to the same retrieval,
memory, policy, tool, confirmation, and trace projections used by the rest of
the console.

```text
Customer message
      |
      v
Context and evidence  ->  Semantic proposal  ->  Deterministic decision
                                                        |
                                                        v
                                      Confirmation / escalation / authority
                                                        |
                                                        v
                                             Bounded agent response
```

The conversation column shows only user-visible messages. The adjacent
activity and runtime panels show observable intent, retrieved sources, policy
outcomes, bounded tool status, memory availability, trace identity, and
authority state. They intentionally omit raw prompts, provider payloads,
hidden reasoning, and tool arguments. This makes the customer experience and
the control-plane decision boundary inspectable without creating a separate
chatbot execution path.

## Architecture

```mermaid
flowchart TB
    USER[User / Support Operator] --> CONSOLE[React Operator Console]
    CONSOLE --> AGENT[Agent Orchestration]
    AGENT --> LLM[LLM semantic proposal\nUNTRUSTED]
    LLM --> VALIDATE[Provenance and target validation]
    VALIDATE --> COMPILER[Decision Compiler]
    COMPILER --> POLICY[Policy Engine]
    POLICY --> CONFIRM[Confirmation Gate]
    CONFIRM --> AUTHORITY[Execution Authority]
    AUTHORITY --> TOOLS[Typed Business Tools]
    TOOLS --> POSTGRES[(PostgreSQL)]
    AGENT --> RAG[RAG / Knowledge]
    RAG --> QDRANT[(Qdrant)]
    AGENT -. bounded metadata .-> OTEL[OpenTelemetry]
    OTEL --> JAEGER[Jaeger]
```

The trust boundary is explicit:

```text
User request
  -> Agent orchestration
  -> Semantic proposal
  -> Provenance validation
  -> Decision Compiler
  -> Policy evaluation
  -> Confirmation or escalation
  -> Execution authority
```

The LLM does not establish customer scope, trusted identifiers, policy outcomes,
or confirmation state. RAG, memory, and observability provide context or
evidence. They do not authorize a business mutation.

```text
Customer request
        |
Context layer
        |
LLM proposal
        |
Decision compiler
        |
Policy / confirmation gate
        |
Controlled runtime execution
```

Model intelligence is not system authority.

### Enterprise identity boundary

Production authentication validates OIDC access tokens through issuer discovery and rotation-aware
JWKS verification, including signature, audience, issuer, subject, and expiration checks. Validated
claims map to a bounded application principal; the server-owned `resolve_customer_scope()` resolver
still decides the effective customer scope before an `ExecutionContext` is created.

Authentication establishes identity. Authorization constrains accessible customer state. The
Decision Compiler, policy and confirmation gates, and controlled runtime remain the only path to a
business effect. Tokens, authorization headers, raw claims, and identity PII are excluded from auth
metrics and logs. See [security.md](docs/security.md) for configuration and trust boundaries.

### Grounded answer generation

Knowledge-only responses use bounded citation-constrained generation. Hybrid
retrieval and reranking select evidence; the answer generator may synthesize
only from those selected chunks. A deterministic grounding validator then
checks citation coverage, excerpt identity, unsupported claims, and source
agreement before the answer is accepted.

When evidence is empty, irrelevant, or conflicting, the response surfaces
uncertainty instead of silently inventing a policy or choosing between sources.
The operator projection exposes source count, citation count, grounding status,
confidence, and unsupported-claim count without exposing hidden reasoning.
This reduces the supported hallucination surface; it is not a claim of perfect
hallucination prevention.

See the detailed [architecture document](docs/architecture.md) for the full system diagram and trust-boundary notes.
The [demonstration scenarios](docs/demo-scenarios.md) summarize the evidence-first walkthrough.
The [production demo showcase](docs/demo-showcase.md) documents the reproducible live/replay scenario suite and screenshot package.
The Playground also offers four read-only [production-style evidence fixtures](docs/demo-showcase.md#production-style-demo-scenarios) for inspecting memory, RAG grounding, deterministic decisions, and authority boundaries without creating a runtime run.

## Core guarantees

The runtime fails closed when the proposal is unsupported or cannot be grounded.

- Model-produced identifiers and arguments do not become trusted facts automatically.
- Deterministic validation checks customer scope, target admissibility, required fields, and business state.
- Risk 2 mutations require confirmation bound to persisted action state.
- Risk 3 work follows a human escalation path.
- Database-backed idempotency prevents duplicate business effects on covered paths.
- Replays cannot resurrect stale or declined confirmations.
- Unknown write outcomes are not blindly replayed.

The platform's safety claim is about authority placement and measured containment. It is not a claim that the model never makes a mistake.

## Demonstrated scenarios

The public showcase uses four deterministic evidence snapshots:

- **Refund with memory and RAG:** Evidence grounds a proposal, then a
  confirmation boundary holds the mutation.
- **Prompt injection defense:** Untrusted scope expansion reaches policy
  evaluation, is prevented, and receives no authority.
- **Duplicate operation protection:** Existing operation state stops a second
  business effect.
- **Missing information clarification:** An incomplete target leads to
  clarification. Execution is not attempted.

The [production demo showcase](docs/demo-showcase.md) describes each scenario
and links to the final screenshot package.

## Validation evidence

The current release candidate has two separate gates:

| Area | Result |
| --- | --- |
| Deterministic evaluation | `110/110` |
| Safety evaluation | `40/40` |
| Resilience evaluation | `28/28` |
| M6.29B D2c semantic and safety validation | `540/540` |
| Unsafe executable survivors | `0` |
| Unsafe executions | `0` |
| M6.34 D2d operational release gate | `D2D_RELEASE_GATE_PASS` |

M6.29B containment evidence:

```text
15 -> 3 -> 0 -> 0 -> 0 executable survivors
```

The full prospective run recorded 30 unsafe semantic proposals, 30 deterministic interventions, zero unsafe executable survivors, and zero unsafe executions. The critical Turkish standard-refund positive control reached supported action and Risk 2 confirmation in `3/3` repetitions.

M6.34 validated the source-bound operational reference deployment:

- `18/18` operational scenarios;
- `8/8` mandatory phases;
- `6/6` fault classes recovered;
- same-action committed effects `1, 1, 1`;
- independent-action committed effects `2, 2, 2`;
- zero duplicate mutations, unauthorized mutations, confirmation bypasses, stale resurrection, declined resurrection, and privacy violations.

Read the [release evidence index](docs/release-evidence.md) for experiment identities, artifact paths, and hashes. Read the [evaluation overview](docs/evaluation-overview.md) for the D2c/D2d gate split and the [D2d contract](docs/d2d-release-gate.md) for operational acceptance criteria.
Future evaluation outputs follow the [evaluation artifact retention policy](docs/evaluation-artifact-policy.md), which keeps compact integrity metadata in Git while allowing large raw attempt dumps to use immutable external storage.

Capacity and cost planning are documented separately in the [capacity report](docs/capacity-report.md)
and [estimated cost model](docs/cost-model.md). These are provider-free measurement and planning
documents, not production SLOs or billing measurements.

## Production Operations

The reference topology exposes process liveness at `/health`, required
dependency readiness at `/ready`, and bounded operator diagnostics at
`/health/details`. Diagnostics include service version, deployment identity,
dependency state, latency summaries, and aggregate retry/circuit/request
signals without prompts, tokens, credentials, or customer data.

Operational ownership and response procedures are documented in the
[alerting strategy](docs/alerting.md), [deployment lifecycle](docs/deployment-lifecycle.md),
[disaster recovery guide](docs/disaster-recovery.md), and [incident runbooks](docs/runbooks/).
Provider outages are treated as degraded dependency conditions; deterministic
validation, confirmation, idempotency, tenant isolation, and controlled
execution remain unchanged.

## Why this architecture exists

Modern LLM agents are useful proposal generators, but probabilistic output
cannot own operational authority. Production-oriented agent systems need a
clear boundary between model intelligence and system authority.

| Problem | Architecture response |
| --- | --- |
| Hallucination risk | Evidence-backed decisions, RAG grounding, and provenance checks keep unsupported proposals from becoming trusted facts. |
| Unsafe agent execution | The decision compiler, policy engine, and confirmation boundaries determine whether a covered action is admissible. |
| Operational failures | Persistence-backed idempotency, duplicate protection, and controlled runtime execution bound business effects. |

The console exposes these observable boundaries and omits hidden reasoning and
model token streams.

## Production Evidence

The public evidence package is organized around four deterministic scenarios:

1. **Refund request with memory + RAG** — Evidence grounds a refund proposal;
   the confirmation boundary remains active and no mutation is performed
   without approval.
2. **Prompt injection defense** — Untrusted scope-expanding input is rejected
   by policy and receives no execution authority.
3. **Duplicate operation protection** — Existing operation state and idempotency
   controls prevent a second business effect.
4. **Missing information clarification** — An incomplete target produces a
   clarification requirement; execution is not attempted.

Each scenario is an evidence snapshot rather than a claim of universal model
reliability. The [showcase guide](docs/demo-showcase.md) explains the operator
workflow and the [release evidence](docs/release-evidence.md) records the
validated D2c and D2d results.

## Investigation and observability

Runs & traces is a read-only operator workflow for inspecting a projected run:

```text
Request → Evidence → Proposal → Decision → Authority
```

The registry and investigation view show bounded evidence, deterministic
decisions, authority state, and outcome. They do not present live telemetry or
direct execution controls.

## Production showcase

The current visual evidence package is under
[`screenshots/demo-final-release-v3/`](screenshots/demo-final-release-v3/). These
screenshots are generated from bounded deterministic projections. They show the
customer request, agent response, evidence, deterministic decision, and authority
outcome—not hidden reasoning, raw provider output, or production telemetry.

### 1. Control plane overview

![Control plane overview](screenshots/demo-final-release-v3/01-control-plane-overview.png)

*Overview of the operator control plane: the product story starts with evidence, explicit guarantees, and bounded authority.*

### 2. Authority boundary architecture

![Authority boundary architecture](screenshots/demo-final-release-v3/07-authority-flow.png)

*Architecture view separating context and model proposals from deterministic decisions and controlled runtime authority.*

### 3. Agent lifecycle scenarios

Each scenario shows the original customer request, the bounded agent response, and
the decision boundary that connects evidence to authority.

#### Refund confirmation

![Refund confirmation boundary](screenshots/demo-final-release-v3/02-refund-confirmation-boundary-v2.png)

*Grounded refund evidence produces a proposal, while the confirmation boundary keeps execution awaiting approval.*

#### Prompt injection defense

![Prompt injection defense](screenshots/demo-final-release-v3/03-prompt-injection-policy-deny-v2.png)

*Untrusted scope expansion is denied by policy and receives no execution authority.*

#### Duplicate operation protection

![Duplicate operation protection](screenshots/demo-final-release-v3/04-idempotency-protection-v2.png)

*An existing refund operation is detected before a second business effect can be created.*

#### Missing information clarification

![Missing information clarification](screenshots/demo-final-release-v3/05-missing-information-clarification-v2.png)

*An incomplete target leads to clarification, with execution explicitly not attempted.*

### 4. Operational run registry

![Operational run registry](screenshots/demo-final-release-v3/06-operational-run-registry.png)

*Runs and traces organize deterministic scenario evidence for operator investigation rather than presenting live telemetry.*

### 5. Investigation report and audit evidence

![Investigation report](screenshots/demo-final-release-v3/08-investigation-report.png)

*Read-only investigation reporting connects available evidence, deterministic decisions, authority state, and outcome without exposing hidden reasoning.*

### 6. Mobile responsive view

![Mobile investigation view](screenshots/demo-final-release-v3/09-mobile-view.png)

*Responsive investigation surface showing that the same evidence and authority boundaries remain available on a narrow viewport.*

For the written architecture tour, see the [architecture document](docs/architecture.md).

## Local demo

### Requirements

- Docker with Docker Compose
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm

### Start the complete stack

```bash
cp .env.example .env
docker compose up --build --detach
```

Open <http://localhost:5173>. The local stack starts PostgreSQL, Qdrant, Jaeger, the backend, and the Operator Console. Setup migrates the database, loads deterministic demo records, and ingests the bundled knowledge base.

A real `/agent/chat` result requires a reachable OpenAI-compatible provider. The local configuration may use Ollama or another explicitly configured provider. Provider calls are not part of the offline evaluation gates.

The Playground offers two explicit modes: **Recorded evidence replay** uses the configured bounded
local path, while **Live proposal run** is enabled only when the server is configured for the
OpenAI API. In live mode the model returns a structured semantic proposal only; deterministic
grounding, compilation, policy, confirmation, and execution-authority checks remain in control.

To generate the bounded public showcase run index and scenario run IDs against the local stack:

```bash
bash scripts/run_demo_suite.sh
```

The suite writes safe metadata and screenshots under `screenshots/demo-final/`; it does not send
confirmation commands or expose raw provider responses.
Without an OpenAI key, the UI falls back to bounded evidence replay and states that fallback
explicitly. See [demo-scenarios.md](docs/demo-scenarios.md#live-proposal-mode) for the scope and
limitations of this optional path.

The live evidence flow is:

```text
Request → Context → LLM proposal → Decision Compiler → Policy → Authority → Evidence
```

For a hermetic integration proof without a live model, run:

```bash
make e2e-smoke
```

The smoke uses an isolated Compose project and fresh volumes, then removes those resources. It validates authenticated request handling, a Risk 2 proposal, persistence across backend restart, one idempotent mutation, replay safety, and bounded Operator Console projections. It does not measure real-model semantic quality.

### Operator Journey Evidence

Browser-level Playwright journeys validate the architecture from the operator's
point of view, not only through backend assertions. The suite covers a grounded
refund proposal held at confirmation, policy containment of prompt injection,
idempotent confirmation replay, clarification for a missing target, a
citation-constrained knowledge answer, and the run-investigation workflow.

The journeys run against an isolated Compose deployment. A local deterministic
proposal fixture supplies structured semantic proposals only; the real compiler,
policy, confirmation, persistence, retrieval, projection, and execution layers
remain in control. No external model endpoint or credential is required.

```bash
npm --prefix frontend ci
npx --prefix frontend playwright install chromium
bash scripts/run_operator_e2e.sh
```

Successful captures are written to `screenshots/operator-e2e/`. The suite does
not expose prompts, raw provider responses, secrets, hidden reasoning, or model
tokens.

Useful local endpoints:

| Service | URL |
| --- | --- |
| Operator Console | <http://localhost:5173> |
| FastAPI | <http://localhost:8000> |
| Jaeger | <http://localhost:16686> |
| Qdrant | <http://localhost:6333> |

Stop the stack with:

```bash
docker compose down
```

See [deployment.md](docs/deployment.md) for health, readiness, container, and production-oriented
Compose details. See [disaster recovery](docs/disaster-recovery.md) for backup, restore, and
evidence-recovery assumptions.

## Testing and CI

Backend quality gates:

```bash
make test
make lint
make typecheck
```

Frontend quality gates:

```bash
make frontend-test
make frontend-typecheck
make frontend-lint
make frontend-build
```

Offline evaluation gates:

```bash
make eval
make eval-safety
make eval-resilience
```

CI also validates dependencies, secrets, Docker/Compose configuration, image policy, six Chromium operator journeys, and the authenticated lifecycle smoke. See [ci.md](docs/ci.md) for the gate graph.

## Project structure

```text
app/                 FastAPI, agent graph, policy, persistence, RAG, tools, observability
evaluation/          Deterministic evaluation and frozen D2d release-gate tooling
frontend/            React, TypeScript, Vite, Tailwind Operator Console
tests/               Backend unit and integration tests
docs/                Architecture, deployment, evaluation, and release evidence
alembic/             Database migrations
scripts/             Seed, ingestion, and integration helpers
docker-compose*.yml  Local, integration, and production-oriented Compose definitions
Makefile             Development and verification commands
```

## Limitations and scope

- This repository is a production-oriented reference implementation, not a production-readiness, enterprise, capacity, or compliance certification.
- Live evidence is bound to exact source, provider, model, prompt, schema, dataset, scorer, and contract identities.
- Model semantic errors can still occur. Deterministic containment does not prove that unseen failures are impossible.
- The Operator Console displays bounded projections and intentionally omits raw prompts, provider responses, secrets, memory bodies, and hidden reasoning.
- The release gate covers the documented single-environment reference deployment. It does not certify public-internet TLS, enterprise IAM, Kubernetes, multi-region operation, disaster recovery, or autoscaling capacity.
- Full application load and capacity characterization, provider cost telemetry, longer soak tests, and stronger chaos exercises remain outside the validated release scope.
- Backend OIDC/JWT validation is included. Browser login, IdP provisioning, session lifecycle, and external secret management remain deployment-owned integration responsibilities.

## Further reading

- [Architecture](docs/architecture.md)
- [Identity and security boundaries](docs/security.md)
- [Distributed reliability boundaries](docs/reliability.md)
- [Memory privacy boundary](docs/memory-privacy.md)
- [Evaluation overview](docs/evaluation-overview.md)
- [Evaluation artifact retention policy](docs/evaluation-artifact-policy.md)
- [Release evidence](docs/release-evidence.md)
- [Public release notes](docs/release-notes.md)
- [D2d operational contract](docs/d2d-release-gate.md)
- [Deployment expectations](docs/deployment.md)
- [Frontend design guidelines](docs/frontend-design-guidelines.md)
