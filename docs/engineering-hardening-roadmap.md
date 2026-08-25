# Engineering Hardening Roadmap

_Production-oriented Agentic AI Control Plane — post-release hardening backlog_

This document is the durable engineering backlog for production-boundary work
identified during the latest main-branch technical review. It is intentionally
not a feature wishlist. The items below are grounded in the current repository
architecture and distinguish confirmed evidence gaps, potential authorization
issues that require confirmation, architectural debt, governance gaps, and
future optimization.

The current baseline already has strong control-plane boundaries: typed tool
execution, `semantic_decision_v3`, a deterministic `DecisionCompiler`, explicit
confirmation and post-confirmation revalidation, idempotency receipts and
database uniqueness, persisted workflows/checkpoints, fail-closed RAG
grounding, memory consent/DLP/TTL/tenant scoping, deterministic QA, real-LLM
QA, and full-stack integration smoke coverage. This roadmap hardens those
boundaries; it should not replace them with more LLM-driven behavior.

## Priority checklist

- [ ] P0 OIDC operator customer-scope audit
- [ ] P0/P1 production checkpoint fail-closed
- [ ] P1 production network topology
- [ ] P1 evaluation evidence alignment
- [ ] P1 PostgreSQL benchmark evidence
- [ ] P2 repository governance
- [ ] P2 structured compiler contracts
- [ ] P2 tool-owned revalidation strategy
- [ ] P2/P3 frontend request/state correctness
- [ ] P3 graph compile benchmark
- [ ] P3 warning cleanup
- [ ] P3 RAG semantic evaluation expansion

## Priority model

- **P0** — security, authorization, or correctness blocker.
- **P1** — production hardening or evidence-correctness gap.
- **P2** — maintainability, contract clarity, or release governance.
- **P3** — optimization, cleanup, or future evaluation depth.

Every item has a primary priority. Shared labels such as `P0/P1` indicate that
the item is a fail-closed production control with both blocker and hardening
implications; `P2/P3` indicates maintainability work that should be addressed
before optimization.

## Existing strengths to preserve

The following controls are established architectural strengths and are not
targets for redesign:

- The LLM proposes semantics; it does not grant execution authority.
- `semantic_decision_v3` and the deterministic `DecisionCompiler` separate
  decision, authority, execution, validation, and workflow state.
- `BusinessTargetResolver`, typed tool inputs, and tool-side scope checks keep
  server-owned identifiers and customer scope out of model authority.
- Policy evaluation, explicit confirmation, post-confirmation revalidation,
  and idempotency receipts protect customer-impacting mutations.
- Database uniqueness constraints, locking where relevant, and unknown-write
  outcomes protect against replay and ambiguous business effects.
- Checkpoint serialization and persistent workflow state support pending
  confirmation, suspend/resume, browser refresh, and backend restart recovery.
- RAG grounding validates excerpts and claims, detects numeric conflicts, and
  fails closed on uncertainty.
- Memory has consent, DLP/security filtering, TTL, and tenant-scope controls;
  memory is not an authorization channel.
- Deterministic integration QA, real-LLM QA, and full-stack authenticated
  smoke provide meaningful evidence for the current release baseline.

Do not weaken these boundaries to improve semantic convenience, demo flow, or
test pass rates.

## Roadmap items

### 1. OIDC operator customer-scope authorization

**Priority:** P0
**Category:** Security / authorization
**Status:** TODO — potential high authorization gap; requires confirmation
**Classification:** Potential issue / requires audit
**Estimated effort:** L

#### Problem

OIDC support-operator principals carry `tenant_id` and `customer_ids`.
Agent/business request paths appear to validate a requested customer against
`customer_ids`, while several operator UI surfaces may enforce only the
`support_operator` role plus tenant scope. The potentially affected surfaces
include:

- `/ui/agent-runs`
- `/ui/agent-runs/{id}`
- `/ui/conversations/{id}`
- `/ui/policy-events/{id}`
- `/ui/policy-audit/{conversation}`
- `/ui/memory/{customer_id}`

The observed model must be confirmed before calling this a vulnerability. An
operator whose allowed customers are `[12, 27]` may be denied for an agent
interaction with customer `91`, while an operator UI lookup for customer `91`
could succeed if the UI is only tenant-scoped.

#### Why it matters

Inconsistent authorization between agent interaction and operator projection
can expose conversations, memory, policy events, or run metadata outside an
operator's intended customer scope. Even when customer-facing anti-enumeration
wording is correct, an over-broad trusted operator projection is a data-access
boundary risk.

#### Current behavior

The review identified a possible difference between `customer_ids` enforcement
in business paths and tenant-only enforcement in UI routes. The intended
meaning of `customer_ids` is not yet established as either a row-level
authorization boundary or an agent-interaction-only restriction.

#### Target behavior

Every path must enforce the documented authorization model consistently. If
`customer_ids` is a row-level boundary, a support operator cannot read a
conversation, run, memory record, policy event, or audit record for a customer
outside that set. If operators are intentionally tenant-wide observers,
customer-wide visibility must be explicit and tested rather than implied by a
field named `customer_ids`.

#### Scope

- OIDC principal and scope semantics.
- UI routes, projection repositories, and service-level access checks.
- Conversation/run, memory, policy-event, and policy-audit lookups.
- Tenant isolation and anti-enumeration behavior.

#### Implementation direction

First determine whether `customer_ids` is a true row-level authorization
boundary. If it is, create one shared primitive such as
`authorize_customer_access(principal, customer_id)` and enforce it at the
repository/service boundary in addition to route checks. If it is not, rename
or document the field semantics and add an explicit tenant-wide operator
authorization model so future code cannot infer the wrong boundary.

#### Acceptance criteria

- No operator path can access a customer outside its intended authorization
  scope.
- Tenant scope remains enforced independently of customer scope.
- Forbidden lookups do not leak existence, amount, status, memory, policy, or
  run metadata through response differences or projections.
- The chosen `customer_ids` semantics are documented in the principal/schema
  contract.

#### Tests and evidence required

- Allowed and forbidden OIDC customer access.
- Direct customer-ID, conversation, run, memory, policy-event, and audit
  lookups.
- Forbidden-customer enumeration and response-shape checks.
- Cross-tenant access denial.
- Regression evidence for both agent and operator paths.

### 2. Production checkpoint backend must fail closed

**Priority:** P0/P1
**Category:** Reliability / correctness / deployment safety
**Status:** TODO
**Classification:** Potential production configuration gap; requires audit
**Estimated effort:** S

#### Problem

Checkpoint persistence is part of workflow correctness because pending
confirmation, suspend/resume, browser refresh recovery, and backend restart
recovery depend on it. The review raised concern that
`APP_ENV=production` with `CHECKPOINT_BACKEND=memory` may still allow startup.

#### Why it matters

An ephemeral checkpoint backend can silently lose a pending action or workflow
boundary on process restart. That creates ambiguity around whether a customer
has confirmed an action and can cause unsafe or confusing recovery behavior.

#### Current behavior

The configuration path must be audited to verify whether production startup
rejects an in-memory checkpoint backend. Memory checkpoints remain appropriate
for development/test environments where explicitly intended.

#### Target behavior

Production startup fails before serving traffic unless the checkpoint backend
is persistent, expected to be PostgreSQL in the current deployment contract.

#### Scope and implementation direction

- Add/verify configuration validation at the startup boundary.
- Keep development and test overrides available where the environment contract
  explicitly permits them.
- Add production Compose/topology validation and operator-facing failure text.
- Document the invariant alongside deployment configuration.

#### Acceptance criteria

- `production + postgres` starts successfully.
- `production + memory` fails deterministically before serving requests.
- `development/test + memory` remains allowed only where intended.
- The failure identifies the persistent-checkpoint requirement without exposing
  secrets or internal stack traces.

#### Tests and evidence required

- Configuration unit tests for the three environment/backend combinations.
- Production Compose validation.
- Startup/readiness evidence proving the invalid combination cannot become
  healthy.
- Recovery regression for pending and suspended workflows.

### 3. Harden production network topology and port exposure

**Priority:** P1
**Category:** Security / deployment hardening
**Status:** TODO
**Classification:** Production topology hardening gap
**Estimated effort:** M

#### Problem

The base Compose configuration publishes ports for infrastructure services
including PostgreSQL, Qdrant HTTP, Qdrant gRPC, Jaeger, and OTLP. The
production override hardens containers with read-only filesystems, dropped
capabilities, `no-new-privileges`, resource limits, authentication, and
persistent audit/projection storage, but it may not remove unnecessary host
port exposure.

#### Why it matters

Publishing internal service ports increases the reachable attack surface and
can make deployment intent unclear. This repository-level issue does not prove
internet exposure; external firewall/VPC controls are outside this audit.

#### Target behavior

Only intended ingress surfaces are published to the host. PostgreSQL, Qdrant,
Jaeger, OTLP, and other internal services communicate over the Docker network
unless a port is explicitly approved for the deployment contract.

#### Scope and implementation direction

- Review base and production Compose files together.
- Define an exact approved host-port allowlist.
- Remove or override forbidden `ports` entries in the production topology.
- Preserve internal service discovery and health checks.
- Extend the production topology validator to reject forbidden published
  ports.

#### Acceptance criteria

- Rendered production Compose exposes only intentionally approved ports.
- Forbidden database, vector-store, tracing, and OTLP ports are not published.
- Backend-to-PostgreSQL/Qdrant connectivity remains functional on the internal
  network.
- Health/readiness checks continue to pass.

#### Tests and evidence required

- Rendered Compose configuration audit.
- Validator tests for allowed and forbidden ports.
- Integration health and internal-connectivity checks.
- Documentation of the approved ingress surface.

### 4. Align evaluation and README evidence semantics

**Priority:** P1
**Category:** Governance / evidence correctness
**Status:** TODO
**Classification:** Confirmed documentation/evidence ambiguity
**Estimated effort:** S

#### Problem

Deterministic runner output may report `110 scenarios` and `96.4% overall`,
while README wording such as `110/110 deterministic` can be read as 100%
scenario success. Historical and current runs can also be conflated if the
public summary does not identify the runner and scope of each number.

#### Why it matters

Release reviewers must be able to map every public metric to a real runner
output. Ambiguous metrics reduce trust in otherwise strong safety evidence.

#### Target behavior

Documentation separates scenario count, overall task/quality score, critical
safety gates, safety suites, resilience suites, historical runs, and current
runs. For example:

```text
Deterministic evaluation: 110 scenarios, 96.4% overall task completion
Safety: 40/40
Resilience: 28/28
Critical safety gate: PASS
```

The example is illustrative; public numbers must come from the corresponding
runner/artifact and must not be invented or merged across runs.

#### Scope and implementation direction

- Audit README, evaluation documentation, release QA reports, and CI artifact
  wording.
- Identify the authoritative output for each metric.
- Update labels to include runner, date/scope, and denominator semantics.
- Investigate artifact-upload steps that report missing files.
- Preserve historical findings rather than rewriting them as current passes.

#### Acceptance criteria

- Every public number maps to a real artifact or documented runner output.
- No `x/x` wording implies scenario perfection unless that is exactly what the
  denominator represents.
- Historical and current evidence are visibly separated.
- Missing evaluation artifacts are either fixed or explicitly reported.

#### Tests and evidence required

- Markdown/link validation.
- Evaluation artifact schema/output check.
- CI artifact-upload dry run or equivalent evidence.
- Reviewer can reproduce the README metrics from named outputs.

### 5. Establish real PostgreSQL concurrency/capacity evidence

**Priority:** P1
**Category:** Reliability / performance evidence
**Status:** TODO
**Classification:** Evidence gap
**Estimated effort:** M

#### Problem

`scripts/benchmark_postgres_capacity.py` can fall back to SQLite when
`CAPACITY_DATABASE_URL` is absent. In that case, output is not evidence of
PostgreSQL capacity. The benchmark also appears to exercise an isolated
persistence/idempotency primitive rather than full agent throughput.

#### Why it matters

SQLite results cannot establish PostgreSQL locking, unique-constraint, or
contention behavior. Naming a fallback result as PostgreSQL capacity can
mislead release and deployment decisions.

#### Target behavior

Correctness benchmarking and real PostgreSQL integration capacity evidence are
separate. No result is named or documented as PostgreSQL capacity unless the
database backend is actually PostgreSQL.

#### Scope and implementation direction

1. Keep or rename the persistence invariant benchmark for same-key behavior,
   unique-key concurrency, and idempotency primitive correctness.
2. Add a PostgreSQL integration concurrency benchmark using the real service,
   unique constraints, locking, contention, and receipt/idempotency boundaries.
3. Provide `CAPACITY_DATABASE_URL` from a dedicated PostgreSQL CI service or
   explicit isolated environment.
4. Record `database_backend` in every result and fail the PostgreSQL benchmark
   when it is not actually using PostgreSQL.

Do not claim this measures whole-platform production throughput unless the
benchmark actually exercises that scope.

#### Acceptance criteria

- SQLite fallback is clearly named as a lightweight invariant benchmark.
- PostgreSQL capacity runs fail closed when PostgreSQL is unavailable.
- Results include backend, workload scope, concurrency, and contention context.
- Documentation distinguishes persistence correctness from platform throughput.

#### Tests and evidence required

- CI job with isolated PostgreSQL.
- Backend identity assertion in benchmark output.
- Repeated-key, unique-key, lock/contention, and receipt semantics results.
- Artifact review confirming no SQLite result is labeled PostgreSQL capacity.

### 6. Add structured decision compiler contracts

**Priority:** P2
**Category:** Correctness / maintainability
**Status:** TODO
**Classification:** Architectural debt
**Estimated effort:** M

#### Problem

Some resumable workflow semantics appear to infer fields from human-readable
reason strings, for example parsing `missing refund reason` to derive
`missing_fields=["reason"]`.

#### Why it matters

Presentation copy is not a stable machine contract. A wording change can
silently alter workflow state, clarification behavior, or execution readiness.

#### Target behavior

The compiler emits structured fields directly, including:

- `reason_code`
- `missing_fields`
- `clarification_fields`

Human-readable `reason` remains presentation-only. No workflow or execution
control logic parses it.

#### Scope and implementation direction

- Audit compiler result schemas and all consumers.
- Add typed fields while preserving bounded operator/customer projections.
- Migrate workflow lifecycle, clarification, and projection consumers to the
  structured fields.
- Keep compatibility adapters only at external boundaries that require them.

#### Acceptance criteria

- No execution or workflow transition depends on parsing human-readable reason
  text.
- Missing-field and reason-code values are typed and validated.
- Projection copy can change without changing workflow semantics.
- Existing confirmation, revalidation, policy, and idempotency behavior is
  unchanged.

#### Tests and evidence required

- Compiler contract tests for every decision state.
- Missing-field and clarification regression tests.
- Property/fixture tests with changed presentation wording.
- Operator projection compatibility tests.

### 7. Evaluate a tool-owned revalidation contract

**Priority:** P2
**Category:** Maintainability / correctness
**Status:** TODO
**Classification:** Architectural debt; audit before refactor
**Estimated effort:** M

#### Problem

Revalidation currently knows specific risky tools centrally. As the registry
grows, adding a new Risk-2 tool may require changes in multiple central
switch-like locations.

#### Why it matters

Distributed registration increases the chance that a new confirmation-required
tool is missing business-state revalidation or is classified inconsistently.

#### Target behavior

Each tool has one obvious typed declaration of its revalidation behavior, for
example a `revalidate` strategy on `AgentToolDefinition` or an equivalent
registry-owned abstraction. The execution authority, confirmation binding,
business revalidation, and idempotency boundaries remain centralized where
they are security-critical.

#### Scope and implementation direction

- Inventory current tools, risk classes, and revalidation call sites.
- Map which semantics are genuinely tool-owned and which must remain global.
- Design a typed strategy/metadata contract before refactoring.
- Add a new-tool contract test that fails if required revalidation is omitted.
- Migrate incrementally only if the ownership boundary becomes clearer.

#### Acceptance criteria

- Adding a confirmation-required tool has one discoverable typed declaration
  for revalidation.
- No tool can bypass confirmation, authority, policy, target checks, or
  idempotency by omission.
- Existing tool behavior and exact pending-action binding remain unchanged.
- Registry validation rejects incomplete Risk-2 definitions.

#### Tests and evidence required

- Tool registry completeness tests.
- Revalidation tests for every current mutation tool.
- New-tool fixture proving missing metadata fails closed.
- Replay and altered-target regression coverage.

### 8. Establish repository and release governance

**Priority:** P2
**Category:** Governance / release engineering
**Status:** TODO
**Classification:** Evidence/governance gap
**Estimated effort:** S

#### Problem

Technical CI quality is strong, but repository governance may lag behind it.
The review reported that main protection and required checks were off, and the
latest commit was unsigned.

#### Why it matters

Strong tests do not prevent a release from bypassing them if the branch and
release process does not require the relevant checks. This is governance, not
runtime architecture.

#### Target behavior

The normal release path protects `main`, requires critical CI checks, disallows
force pushes, and uses a documented PR/release process. Signed release tags
should be adopted where practical; commit signing policy should be explicit
rather than assumed.

#### Scope and implementation direction

- Audit branch protection and required-check configuration.
- Define the minimal required backend, frontend, E2E, and security/release
  evidence checks.
- Disallow force pushes to the release branch.
- Document PR, release-tag, and signing expectations.
- Keep emergency procedures explicit and auditable.

#### Acceptance criteria

- A normal release cannot bypass the required automated safety/test gates.
- Main branch protection and force-push policy are verifiable.
- Required checks are named and match the current CI jobs.
- Release tags and signing expectations are documented.

#### Tests and evidence required

- Repository settings audit/export.
- Protected-branch negative-path test where supported.
- CI check-name review.
- Release checklist update with no invented status claims.

### 9. Improve frontend operator state ownership and stale-request safety

**Priority:** P2/P3
**Category:** Correctness / maintainability
**Status:** TODO
**Classification:** Architectural debt with a potential stale-state bug
**Estimated effort:** M

#### Problem

`App.tsx` has accumulated authentication, health, runtime configuration,
memory, recent runs, demo runs, route handling, chat, investigation state, and
navigation responsibilities. A request such as `api.memory(customerId).then(setMemory)`
can render stale customer A data after the operator has switched to customer B:

```text
A starts
B starts
B finishes
A finishes -> stale A state may render
```

#### Why it matters

Operator projections are trusted operational evidence. Stale memory or run data
can confuse investigation and scope review even if backend authorization is
correct.

#### Target behavior

Rapid customer/context changes cannot commit a response for an obsolete
selection. Canonical decision, authority, execution, validation, and security
state continues to come from the backend projection; the frontend does not
reconstruct those states from unrelated fields.

#### Scope and implementation direction

- Identify asynchronous requests keyed by customer, conversation, run, or
  route selection.
- Use `AbortController`, request generation/version IDs, or focused hooks to
  cancel or ignore stale responses.
- Extract ownership into focused hooks only where it improves correctness.
- Avoid a framework/query-library migration unless it is justified by the
  request graph and current maintenance burden.

#### Acceptance criteria

- Switching customers or runs during in-flight requests cannot display stale
  data.
- Unmounted views do not commit obsolete responses.
- Loading/error states are scoped to the active request key.
- Backend projection remains the sole authority for operator decision fields.

#### Tests and evidence required

- Race test with delayed A/B responses.
- Rapid route/customer switching test.
- Operator projection contract tests ensuring no frontend inference.
- Refresh/recovery regression remains green.

### 10. Benchmark graph compilation before refactoring

**Priority:** P3
**Category:** Performance / maintainability
**Status:** TODO
**Classification:** Future optimization; measure first
**Estimated effort:** M

#### Problem

`AgentRuntime.run()` appears to rebuild or compile the graph per invocation
because node closures contain request-specific dependencies. A future design
could use an immutable compiled graph plus a per-run dependency/context
container, but the benefit is not yet established.

#### Why it matters

Premature graph reuse could weaken request/session isolation. Conversely, if
compile time is material, it may add avoidable latency under concurrency.

#### Target behavior

Measure graph build/compile time, total request latency, memory impact, and
concurrency behavior before deciding whether to refactor. If compile overhead is
negligible compared with provider latency, document the decision and leave the
architecture unchanged.

#### Scope and implementation direction

- Add measurement at existing runtime boundaries without changing semantics.
- Compare cold and repeated invocation cost.
- Measure provider, RAG, policy, and tool stages separately where telemetry
  already supports it.
- Only then evaluate immutable graph plus per-run context injection.

#### Acceptance criteria

- A benchmark report identifies compile time and its percentage of request
  latency.
- Concurrency and memory impact are measured or explicitly unavailable.
- Any refactor preserves request/session isolation and workflow semantics.
- No optimization is merged solely because the graph is rebuilt.

#### Tests and evidence required

- Benchmark under representative deterministic and real-provider timing
  profiles where available.
- Concurrent-session isolation test.
- Pending workflow and idempotency regression after any refactor.

### 11. Reduce CI warning debt

**Priority:** P3
**Category:** Maintainability / release engineering
**Status:** TODO
**Classification:** Confirmed signal-to-noise problem
**Estimated effort:** M

#### Problem

The latest backend run reportedly emits roughly 11,000 warnings. Likely sources
include `datetime.utcnow()` deprecations and TestClient/httpx deprecations.

#### Why it matters

Warning volume hides new correctness and security warnings. Turning all current
warnings into errors immediately would create a noisy, brittle migration rather
than a useful release gate.

#### Target behavior

Warning categories and counts are inventoried, safe migrations are completed,
and CI maintains a small documented baseline. Only after the baseline is low
should selected categories become warnings-as-errors.

#### Scope and implementation direction

1. Capture warnings by category and source.
2. Migrate timezone handling safely, preserving serialized formats and boundary
   semantics.
3. Update deprecated test-client usage/dependencies where appropriate.
4. Establish a baseline and trend check.
5. Promote only selected, actionable categories to errors.

#### Acceptance criteria

- Warning inventory has reproducible category/count output.
- High-volume known warnings are reduced without changing time semantics.
- CI exposes regressions against the documented baseline.
- New actionable warnings remain visible.

#### Tests and evidence required

- Full backend test warning report before and after.
- Timezone/serialization regression tests.
- HTTP client compatibility tests.
- CI baseline check.

### 12. Extend RAG semantic-quality evaluation

**Priority:** P3
**Category:** Quality / evaluation / maintainability
**Status:** TODO
**Classification:** Future evaluation depth; not a current release blocker
**Estimated effort:** M

#### Problem

Current grounding is strong for citation integrity, excerpt validation,
claim/excerpt coverage, numeric conflict detection, and fail-closed
uncertainty. It is not a universal semantic truth judge.

#### Why it matters

A response can be well-cited yet still use the wrong policy applicability,
language interpretation, effective date, or topic. These limits should be
measured rather than implied away by a grounding score.

#### Target behavior

The evaluation suite measures qualitative contradiction, policy applicability,
multilingual semantic retrieval, false abstention, wrong-topic evidence,
freshness, and effective-date conflicts. Runtime grounding remains fail closed;
the task is to improve evidence about quality, not to lower thresholds globally.

#### Scope and implementation direction

- Add a focused evaluation set for eligibility versus processing time,
  multilingual conditions, unsupported questions, contradictory documents, and
  stale/future policy versions.
- Record retrieval relevance, accepted/rejected evidence, abstention, and
  wrong-topic answer rates.
- Keep customer citations separate from bounded operator evidence.
- Document what grounding validates and what it cannot establish.

#### Acceptance criteria

- The evaluation distinguishes grounding integrity from semantic correctness.
- False abstention and wrong-topic evidence are measurable from real artifacts.
- Freshness/effective-date behavior is explicit where the corpus supports it.
- Unsupported questions remain abstentions rather than being made easier to
  answer.

#### Tests and evidence required

- English and Turkish focused RAG evaluation set.
- Retrieval/grounding result artifacts with evidence IDs and acceptance state.
- Human-reviewed qualitative labels for contradiction/applicability cases.
- No fabricated scores when a metric is not exposed.

## Recommended execution order

1. Confirm and, if necessary, fix OIDC operator customer-scope semantics.
2. Enforce a persistent production checkpoint backend fail-closed.
3. Harden production network exposure and the topology validator.
4. Align README and evaluation evidence semantics.
5. Add real PostgreSQL concurrency/capacity evidence.
6. Harden repository governance.
7. Structure compiler and revalidation contracts.
8. Clean up frontend stale-request/state ownership boundaries.
9. Benchmark graph compilation before considering a refactor.
10. Reduce CI warning debt.
11. Extend RAG semantic-quality evaluation.

New agent features, additional tools, and multi-agent expansion should remain
lower priority until the hardening work above is complete.

## Review labels and release discipline

This backlog uses the following evidence labels:

- **Confirmed issue** — current behavior or documentation is directly
  established by repository evidence.
- **Potential issue / requires audit** — a plausible boundary gap was observed,
  but intended semantics or current enforcement must be confirmed before
  calling it a vulnerability.
- **Architectural debt** — current behavior may be safe, but ownership or
  contract structure creates future defect risk.
- **Evidence/governance gap** — the implementation may be sound, but public
  claims or release controls are not yet sufficiently precise or enforced.
- **Future optimization** — a measurement or cleanup opportunity that is not a
  current safety blocker.

Each item should be closed with evidence against its acceptance criteria. Do not
upgrade a release label, rewrite historical QA results, or broaden a claim
without a corresponding artifact or reproducible test result.
