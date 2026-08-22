# D2d Release-Candidate Operational Gate

Status: **CONTRACT FROZEN — HARNESS NOT IMPLEMENTED**

Contract: `d2d_release_candidate_operational_v1`

Machine-readable source: [`evaluation/d2d_spec.py`](../evaluation/d2d_spec.py)

## Purpose

D2d answers:

> Can the current release candidate operate as a production-oriented reference deployment under
> controlled end-to-end operational conditions while preserving deterministic safety, persistence,
> recovery, observability, and idempotency guarantees?

D2d is an operational release-candidate gate, not another model-quality benchmark. D2c owns
semantic model behavior, semantic attribution, and prospective model safety evaluation. Core D2d
uses the repository's deterministic integration provider and makes zero OpenAI model-list or
inference calls.

The validated deployment scope is a **production-oriented single-environment reference
deployment** using the repository's Compose topology:

- PostgreSQL (`db`);
- Qdrant (`qdrant`);
- migration/seed/ingestion bootstrap (`demo-setup`);
- backend API (`backend`);
- frontend/operator console (`frontend`); and
- OpenTelemetry/Jaeger (`jaeger`).

The D2d environment must use isolated volumes, deterministic identities/data, and an explicitly
controlled environment. Developer-local `.env` values must not silently change the run contract.

## Non-goals

D2d v1 does not certify model quality, prompt quality, RAG quality, throughput, capacity,
multi-region behavior, Kubernetes, Terraform, cloud infrastructure, enterprise IAM/OIDC, public
Internet TLS termination, SOC2/GDPR/HIPAA compliance, exact provider cost, voice, multi-agent
workflows, or new product tools. These remain future hardening or V2 scope.

Full load and throughput benchmarking is `POST_RC_HARDENING`. Exact LLM cost accounting is
`NON_BLOCKING_POST_RC_HARDENING`.

## Frozen phases

1. `D2D-0_ENVIRONMENT_FREEZE` — record source, configuration, services, images, dependencies, and
   contract identity.
2. `D2D-1_CLEAN_BOOTSTRAP` — start fresh volumes, migrate to Alembic head `20260812_0007`, seed,
   ingest, and establish readiness.
3. `D2D-2_BASELINE_FUNCTIONAL_E2E` — exercise a safe read, Risk-2 confirmation/persistence, and a
   supported Risk-3 escalation/control flow.
4. `D2D-3_CONCURRENCY_IDEMPOTENCY` — test same-action contention and independent-action control.
5. `D2D-4_RESTART_PERSISTENCE` — test pending, completed/replayed, declined, and stale
   confirmations across backend restart.
6. `D2D-5_FAILURE_RECOVERY` — exercise the frozen dependency-failure matrix and state-based
   recovery assertions.
7. `D2D-6_OBSERVABILITY_PRIVACY` — verify representative traces and bounded privacy-safe evidence.
8. `D2D-7_FINAL_INTEGRITY` — recompute identities, hashes, invariants, and final gate status.

## Mandatory operational scenarios

The machine-readable specification freezes the ordered scenario set, including:

- clean bootstrap and mandatory-dependency readiness;
- safe read, Risk-2 confirmation, and Risk-3 escalation;
- 16-way same-action contention for 3 rounds;
- 2-way independent-action control for 3 rounds;
- pending, completed/replay, declined, and stale confirmation restart cases;
- unknown-write acknowledgement recovery;
- PostgreSQL, Qdrant, provider-timeout, malformed-output, and telemetry-collector failures; and
- observability/privacy scanning.

Some scenarios are marked `HARNESS_REQUIRED` because the current repository has the state or
integration behavior but not yet the dedicated D2d execution seam. This is a harness milestone
requirement, not a runtime behavior change or a product defect.

## Acceptance criteria

D2d has no weighted aggregate score. Every mandatory phase must pass.

The same-action concurrency gate requires, per round:

- exactly one committed business effect;
- zero duplicate or unauthorized mutations;
- zero confirmation bypasses; and
- safe resolution for every other contender.

The independent-action control requires each distinct valid action to commit exactly once. These
are correctness/race checks, not capacity claims.

Pending confirmations must survive restart while valid. Completed actions must remain idempotent
after restart. Declined and stale confirmations must remain non-executable. Recovery is judged by
state, not an invented timing SLO; `TIMING_SLO_NOT_PART_OF_D2D_V1`.

The following are zero-tolerance failures:

- migration failure or inability to become ready;
- unsafe executable action, confirmation bypass, unauthorized mutation, or duplicate mutation;
- stale/declined confirmation resurrection;
- more than one committed effect in a same-action race;
- persistence corruption after restart;
- unrecovered mandatory dependency failure;
- missing required observability evidence;
- privacy violation;
- malformed/incomplete artifacts; or
- source/configuration identity drift.

## Failure and recovery matrix

The mandatory matrix is intentionally small:

| Fault | Required behavior |
| --- | --- |
| PostgreSQL unavailable | readiness becomes not ready; writes fail safely; readiness and a subsequent safe request recover after restoration |
| Qdrant unavailable | existing retrieval-degradation semantics apply; retrieval cannot gain action authority; healthy behavior returns after restoration |
| Deterministic provider timeout | existing failure taxonomy applies; no unsafe action; later request succeeds after fault removal |
| Deterministic malformed output | existing malformed-output taxonomy applies; no unsafe action; later valid request succeeds |
| Jaeger/OTLP unavailable | telemetry remains non-authoritative; business state remains safe and coherent |
| Unknown write acknowledgement | existing idempotency/reconciliation behavior produces at most one committed effect; dedicated harness seam required if needed |

No arbitrary recovery latency target is part of v1.

## Observability and privacy

Representative safe-read, Risk-2, guarded/blocked, and failure/recovery flows must expose bounded
operational evidence for correlation/run identity, runtime stage, tools where applicable, policy,
confirmation, guard intervention, failure category, and recovery path.

Canonical D2d artifacts must contain no raw user text, prompts, provider payloads, refund reasons,
chain-of-thought, secrets, unrestricted memory, or unrestricted RAG content. Published D2d privacy
violations must equal zero. Raw container logs are debugging material, not canonical evidence.

## Artifacts

An atomic, non-overwriting D2d publication contains exactly these canonical files:

- `manifest.json` — identity and integrity manifest;
- `environment.json` — source, configuration, services/images/dependencies, and Alembic head;
- `attempts.json` — bounded phase/scenario records;
- `summary.json` — machine-readable gate dimensions and final status; and
- `summary.md` — human-readable release-gate report.

Each attempt record is limited to phase/scenario identity, ordinal/timing, status, failure
category, health/readiness, migration, confirmation, mutation count, recovery, observability, and
privacy assertions. Every file receives a SHA-256. A partial run is `INVALID`, never `COMPLETE`.

## Approval and rerun policy

The future approval binds experiment ID, exact source revision, this contract version and SHA,
environment/configuration identity, container/image identities, Alembic head, schedule SHA,
concurrency parameters, fault-matrix identity, artifact schema, and retry/rerun policy.

Provider/model identity is `NOT_APPLICABLE` for the provider-independent core. OpenAI model-list
calls, OpenAI inference calls, and Ollama calls are zero.

Per-test automatic retry is zero. Automatic full-run rerun is zero. Patch-and-continue is
forbidden. An invalid consumed run requires a new approval.

Allowed final classifications are:

- `D2D_RELEASE_GATE_PASS`;
- `D2D_PRODUCT_SAFETY_FAILURE`;
- `D2D_CONCURRENCY_IDEMPOTENCY_FAILURE`;
- `D2D_PERSISTENCE_RECOVERY_FAILURE`;
- `D2D_DEPLOYMENT_READINESS_FAILURE`;
- `D2D_OBSERVABILITY_PRIVACY_FAILURE`; and
- `D2D_EXECUTION_INVALID_OR_INCOMPLETE`.

A passing D2d gate supports the bounded statement “production-oriented reference implementation
with prospectively validated semantic safety and operational release-gate evidence.” It does not
mean unrestricted production readiness or compliance certification.
