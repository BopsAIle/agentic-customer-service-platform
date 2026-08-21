# Agentic Customer Service Platform

> Building AI agents that can fail safely.

Production-oriented reference implementation for customer operations built around one principle:

> **The LLM proposes; deterministic software decides what may execute.**

This is not just a LangGraph, RAG, or tool-calling demo. The model emits an untrusted semantic
proposal. Real-world actions pass through server-owned grounding, target admissibility,
deterministic compilation, customer-scoped business validation, policy, confirmation, idempotency,
and audit controls before execution.

The goal is not to make the LLM incapable of making mistakes. The goal is to make model mistakes
non-authoritative.

### Current prospective evidence

Latest live robustness validation: `d2c_m6_20_semantic_v3_20260814T011440Z`

- 540 measured executions across 180 scenarios × 3 repetitions
- Deterministic evaluation: `110/110`
- Safety evaluation: `40/40`
- Resilience evaluation: `28/28`
- Consistency: `172/180` (`95.56%`)

Containment funnel:

```text
29 unsafe semantic proposals
  → 26 deterministic guard interventions
  → 3 unsafe executable survivors
  → 0 unsafe executions
```

Additional execution-safety results: **0 confirmation bypasses**, **0 unauthorized mutations**,
**0 duplicate mutations**, and **0 hallucinated identifiers**. Unsafe executable survivors improved
from **15 to 3** between the comparable prospective runs: an **80% reduction in unsafe executable
survivors**, not an 80% reduction in model errors or hallucinations.

The remaining three survivors are Turkish `amb-refund-no-reason` repetitions. They reached an
executable confirmation-required proposal state but did not execute. The pre-execution containment
gate therefore remains open and D2d is blocked. The next step is offline root-cause analysis and a
deterministic containment fix; this README does not claim production readiness.

## What makes this different?

Most agent demos stop at tool calling. This project focuses on what happens when the model is
wrong:

- **LLM outputs are untrusted.** Model-produced identifiers, targets, and required business
  arguments do not become executable truth without server-owned grounding and validation.
- **Execution authority is deterministic.** Grounding, target admissibility, `DecisionCompiler`,
  customer-scoped resolution, business validation, policy, and confirmation sit between semantic
  output and mutations.
- **Confirmation binds to a stored action.** Approval applies to a persisted pending action that is
  revalidated before execution; the model cannot recreate or self-confirm it.
- **Writes are replay-aware.** Stable action/request identities and database idempotency protections
  prevent blind duplicate mutations; unknown write outcomes are not automatically replayed.
- **Evaluation is evidence, not a demo script.** Frozen bilingual scenarios, source-bound approvals,
  immutable hashes, explicit budgets, and prospective safety gates make failures reproducible and
  distinguish model quality from runtime containment and execution safety.

**The memorable architecture boundary is simple: the LLM proposes; deterministic software
executes.**

Core stack: Python, FastAPI, LangGraph, PostgreSQL, Qdrant, OpenTelemetry, React, and TypeScript.

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

    GRAPH --> SEMANTIC[semantic_decision_v3<br/>UNTRUSTED MODEL PROPOSAL]
    SEMANTIC --> BOUNDARY[SERVER-OWNED DETERMINISTIC BOUNDARY]
    BOUNDARY --> GROUND[Grounding]
    GROUND --> ADMISSIBLE[Target admissibility]
    ADMISSIBLE --> COMPILER[Deterministic DecisionCompiler]
    COMPILER --> RESOLVER[Customer-scoped resolver]
    RESOLVER --> POLICY[Business validation / policy]
    POLICY --> CONFIRM[Confirmation or escalation]
    CONFIRM --> EXECUTE[Validated execution]
    EXECUTE --> TOOLS[Typed Business Tools]
    GRAPH --> MEMORY[Customer-scoped Memory]
    GRAPH --> RAG[Configured RAG Runtime]

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

The canonical semantic path is:

```text
user request
  → context loading
  → semantic_decision_v3
  → semantic entity grounding
  → target admissibility
  → deterministic DecisionCompiler
  → BusinessTargetResolver where permitted
  → business validation
  → policy
  → confirmation or human escalation
  → execution and observability
```

The LLM proposes semantic intent, request type, and typed references. It does not directly own
business tools, customer scope, trusted identifiers, business truth, policy outcomes, or
confirmation state. Executable actions are constructed and authorized by the server.

## Failure-driven hardening

A prospective live evaluation exposed 15 semantic failures that reached executable,
confirmation-required action state. The engineering response was not to hide the result behind a
prompt tweak:

1. failures were attributed by runtime stage;
2. containment gaps were reproduced through the real execution path;
3. deterministic boundaries were hardened;
4. `containment_observability_v1` was added to separate model errors, guard intervention,
   executable survivors, and execution;
5. the frozen prospective evaluation was rerun.

The result was **15 → 3 unsafe executable survivors** while unsafe executions remained **0 → 0**.
The remaining three Turkish `amb-refund-no-reason` cases are still a runtime containment blocker.
This is the useful distinction in the evidence: model semantic quality, pre-execution containment,
execution safety, and production readiness are separate claims.

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

The LangGraph state machine uses typed state, deterministic routing, and Pydantic-validated structured
decisions. The graph separates semantic understanding, deterministic action compilation, validation,
policy evaluation, confirmation, retrieval, memory, execution, and response construction.

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

The repository separates four questions that are often conflated in agent evaluations:

1. model semantic quality;
2. deterministic runtime containment;
3. execution safety; and
4. production readiness.

The evaluation system includes deterministic regression, safety and resilience suites, structured
contract compatibility gates, architecture comparisons, and approval-gated live robustness runs.
Live results are evidence for a particular model, provider, contract, dataset, and source revision;
they are not a certification of unrestricted deployment.

The deterministic offline harness executes versioned scenarios through the real control-plane
paths with isolated state, fake structured-decision inputs, and scoped fault injection. It stores
no chain-of-thought.

Current verified offline results:

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

These are deterministic regression results, not claims about live-model behavior or production
traffic. Runtime RAG evaluation hooks separately report retrieval success, citation availability,
reranker use, fallback behavior, and latency; they do not turn retrieval scores into claims about
live-model answer accuracy.

#### Current validation status

The latest prospective live robustness run is M6.20B,
`d2c_m6_20_semantic_v3_20260814T011440Z`. It used `semantic_decision_v3`,
`gpt-5.6-luna` through the official OpenAI API, frozen `live_eval_v2`, 180 scenarios × 3
repetitions (540 measured executions), one warmup outside the denominator, retry count zero, and
`containment_observability_v1`.

| Layer / metric | Latest evidence |
| --- | ---: |
| Deterministic evaluation | 110/110 |
| Safety evaluation | 40/40 |
| Resilience evaluation | 28/28 |
| Latest prospective D2c | 540/540 measured |
| Provider success | 528/540 |
| Structured output | 522/540 |
| Schema validity | 522/540 |
| Intent correctness | 482/522 |
| Semantic target correctness | 516/522 |
| Clarification correctness | 496/522 |
| Compiler correctness | 487/522 |
| Resolver metric | 225/372 |
| Consistency | 172/180 |
| Unsafe semantic proposals | 29 |
| Deterministic guard interventions | 26 |
| Unsafe executable proposals after guards | 3 |
| Unsafe executions | 0 |
| Confirmation bypasses | 0 |
| Unauthorized mutations | 0 |
| Duplicate mutations | 0 |
| Hallucinated identifiers | 0 |

The containment funnel is explicit: 29 unsafe semantic proposals → 26 deterministic guard
interventions → 26/29 pre-execution contained → 3 executable confirmation-required survivors →
0 unsafe executions. The three survivors are not unsafe executions; they are a remaining
pre-execution containment blocker. The observed containment rate was `26/29 = 89.66%`.

Compared with M6.15B, unsafe executable survivors improved from 15 to 3, an 80% reduction in
surviving executable proposals. Unsafe semantic proposals increased from 15 to 29 between the
independent hosted runs; the model and prompt were unchanged, and temperature zero does not make
separate hosted runs identical. This is not evidence of improved model semantic quality.

| Metric | M6.15B | M6.20B | Delta |
| --- | ---: | ---: | ---: |
| Provider success | 528/540 | 528/540 | 0 |
| Structured output | 522/540 | 522/540 | 0 |
| Schema validity | 522/540 | 522/540 | 0 |
| Raw routing | 209/540 | 217/540 | +8 |
| Intent | 484/522 | 482/522 | -2 |
| Semantic target | 516/522 | 516/522 | 0 |
| Clarification | 487/522 | 496/522 | +9 |
| Compiler | 479/522 | 487/522 | +8 |
| Resolver | 231/372 | 225/372 | -6 |
| Consistency | 171/180 | 172/180 | +1 |
| Unsafe semantic proposals | 15 | 29 | +14 |
| Unsafe executable survivors | 15 | 3 | -12 |
| Unsafe executions | 0 | 0 | 0 |

The previously observed contradictory-cancellation cluster had 6 executable survivors in M6.15B
and 0 in M6.20B. The previously identified invented-reason shapes were contained, but three new
survivors remain in `amb-refund-no-reason` (Turkish repetitions). These were unsafe semantic
proposals that did not trigger deterministic guard intervention, reached an executable refund
action with confirmation required, and did not execute.

M6.16 validated the exact prior survivor shapes offline through the real runtime path, and M6.19
added `containment_observability_v1`. M6.20B is the first prospective run that directly measured
the model-unsafe → guard-intervention → executable-survivor → execution chain. The current
engineering decision is `PRODUCT_RUNTIME_FIX_REQUIRED`; D2d remains blocked.

M6.20B latency was 1278.99 ms provider mean / 1736.25 ms p95 and 1290.28 ms end-to-end mean /
1748.95 ms p95. Usage and cost metadata were unavailable.

Raw routing from M6.20B was `217/540`. It is retained for reproducibility, but it is not a
standalone architecture, safety, or readiness metric: offline attribution identified substantial
oracle/path representation effects, including valid semantic equivalents and oracle mismatches.

The covered positive controls showed no broad over-blocking regression: clear cancellation retained
its normal Risk-2 confirmation flow, grounded refunds retained their normal confirmation flow,
first-time Risk-2 confirmation remained available, refund eligibility and cancellation explanation
remained knowledge-and-action paths, declined/stale confirmation was not resurrected, and safe
reads were not broadly suppressed. These observations do not prove all possible valid flows are
regression-free.

The release-hardening source now contains a narrow deterministic refund-reason provenance fix. It
fails closed when the proposed reason is absent, contains only refund/request boilerplate, or adds
unsupported qualifiers; bilingual explicit reasons remain on the normal Risk-2 path. Focused
offline tests and the existing deterministic, safety, resilience, grounding, admissibility,
policy, confirmation, and replay suites validate the local behavior. The historical M6.20B result
is unchanged: a new source-bound prospective D2c run is still required to verify that the three
Turkish survivors become zero before the P0 blocker is closed.

#### Model/runtime compatibility

The semantic architecture is contract-specific. The recorded V3 compatibility gate found high
structured-output compatibility for `gpt-5.6-luna`. The tested local candidates
`qwen3.5:4b`, `qwen3.5:9b`, and `qwen2.5:7b-instruct` did not meet the frozen
`semantic_decision_v3` compatibility gate under their evaluated Ollama/function-calling
configurations. This does not make a universal claim about Qwen models; it means those exact
model/runtime identities were not eligible for the next behavioral matrix under that contract.

The current evidence uses Luna as the hosted evaluation control, not as a hardcoded production
model or universal recommendation. Local OpenAI-compatible/Ollama integration remains available,
but every model must pass the same structured-contract compatibility gate first.

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

1. **The LLM proposes.** It produces a typed intent, request type, and semantic references. Its
   output is untrusted input to the control plane.
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

### Deterministic semantic guards

The server-owned compiler and validation boundary fails closed for covered unsafe semantic shapes:

- missing or ambiguous destructive targets require clarification;
- contradictory cancellation does not become an executable cancellation proposal;
- an unsupported or invented refund reason requires clarification instead of becoming a refund
  proposal;
- a user-grounded refund reason can continue through the normal validation and confirmation flow;
- memory, retrieval content, and model-produced trust flags are not proof that the user supplied a
  required destructive business argument.

These controls reduce reliance on model correctness, but they do not make arbitrary model behavior
safe by definition. Model semantic errors, runtime containment, and actual execution safety remain
separate evaluation dimensions.

## Historical architecture and model evidence

Model selection was evaluated empirically through the same agent runtime and deterministic
control plane used for evaluation. The LLM output is an untrusted proposal: the model produces
semantic intent, request type, and typed references, while the deterministic control plane remains
responsible for validation, policy enforcement, confirmation requirements, execution safety, and
the audit lifecycle.

### Evaluation Setup

The canonical architecture decision compared `direct_tool_v1` and `semantic_decision_v3` with
the same `gpt-5.6-luna` model, official OpenAI API provider, configuration, dataset, schedule,
and deterministic safety stack. The corrected offline result used immutable outputs and did not
regenerate model calls:

| Measure | Direct | Semantic V3 |
|---|---:|---:|
| Routing | 69/84 (82.14%) | 79/84 (94.05%) |
| Effective clarification | 69/84 (82.14%) | 79/84 (94.05%) |
| Case-level wins | 1 | 6 |

This selected `semantic_decision_v3` as the canonical semantic architecture for subsequent model
evaluation. It did not change the current runtime default, which remains `direct_tool_v1`.

### Findings

#### Compatibility is contract-specific

The V3 compatibility gate is separate from behavioral quality. Luna produced 24/24 typed V3
decisions in the hosted control. The tested local Qwen identities did not meet the same frozen
structured-contract gate, so they were not promoted to the behavioral matrix. These results do not
rank model families universally and do not imply that the current runtime default changed.

### Key Takeaway

Model selection is treated as an engineering decision: first validate the fixed semantic contract,
then measure behavior and runtime trade-offs for eligible candidates.

```text
Measure
   ↓
Identify failure modes
   ↓
Benchmark candidates
   ↓
Choose deployment model based on workload trade-offs
```

The control plane remains authoritative regardless of the underlying model:

```text
LLM proposal
      ↓
Typed decision validation
      ↓
Policy evaluation
      ↓
Confirmation / revalidation
      ↓
Idempotent execution
      ↓
Audit lifecycle
```

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

## Known Limitations

- This is a production-oriented reference implementation, not a production-readiness
  certification or unrestricted deployment approval.
- Current live evidence is bound to exact model, provider, contract, dataset, scorer, and source
  identities.
- The tested local models did not satisfy the frozen `semantic_decision_v3` compatibility gate.
- Raw routing includes known oracle/path attribution noise and is not sufficient as a standalone
  safety or architecture metric.
- Model semantic errors can still occur; deterministic guards, policy, confirmation, and business
  validation are separate containment boundaries rather than proof of model correctness.
- The latest prospective run reduced unsafe executable survivors from 15 to 3 while preserving
  zero unsafe executions. The remaining three survivors are Turkish `amb-refund-no-reason` cases
  and require offline root-cause analysis and a deterministic containment fix before another
  prospective validation and before D2d consideration.
- Provider usage/cost metadata may be unavailable in live evaluation artifacts.
- Synthetic evaluation coverage cannot prove the absence of unseen failure modes.

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

- [x] Perform offline root-cause analysis of the three Turkish `amb-refund-no-reason` survivors
- [x] Implement and validate the required deterministic containment fix offline
- [ ] Create a new source-bound approval and run prospective D2c validation
- [ ] Reconsider the D2d model matrix only after prospective containment passes
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

### Optional legacy live-provider diagnostic

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
confirmation bypass. This is a legacy diagnostic path, distinct from the frozen `live_eval_v2`
D2c workflow, and reports can be compared with:

```bash
python -m evaluation.live compare baseline.json candidate.json
```

The local Ollama model is a development baseline, not validated `semantic_decision_v3` evidence or
a production recommendation. This diagnostic is non-deterministic and machine-dependent; it is
not the canonical D2c path. The approval-gated D2c workflow uses frozen `live_eval_v2`, the fixed
V3 contract, and an explicitly approved hosted runtime. Ollama is optional and never a silent
fallback for deterministic or hosted providers.
