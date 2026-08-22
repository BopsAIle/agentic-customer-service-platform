# Release Evidence

## Release Candidate Overview

This document consolidates the current release candidate's prospective semantic and operational
evidence. It describes a **production-oriented reference validation**, not unrestricted production
certification, enterprise deployment certification, capacity certification, or compliance
certification.

The system scope is an agentic customer-service platform whose architecture keeps execution
authority outside the model:

> **The LLM proposes; deterministic software decides what may execute.**

Model proposals pass through server-owned grounding, target admissibility, deterministic
compilation, customer-scoped business validation, policy, confirmation, idempotency, persistence,
and audit boundaries before business effects are allowed.

Validated release-candidate milestones:

- **M6.29B** — full prospective D2c semantic/safety validation;
- **M6.34** — prospective D2d operational release-gate execution; and
- **M6.35** — consolidation of the immutable evidence references in this document.

## D2c Semantic Safety Evidence

M6.29B completed the canonical full prospective D2c experiment:

| Field | Value |
| --- | --- |
| Experiment | `d2c_m6_29_semantic_v3_20260822T011436Z` |
| Source | `3ae1489fcb9350ddf7f6319e3a67bf7aa5d7f859` |
| Contract | `semantic_decision_v3` |
| Dataset | `live_eval_v2` |
| Measured attempts | `540/540` |
| Classification | `D2C_COMPLETE_SAFETY_CLEAN` |

The deterministic containment funnel was:

```text
15 → 3 → 0 → 0 → 0 executable survivors
```

For M6.29B specifically:

- unsafe semantic proposals: `30`;
- deterministic guard interventions: `30`;
- unsafe executable survivors after guards: `0`;
- unsafe executions: `0`;
- confirmation bypasses: `0`;
- unauthorized mutations: `0`;
- duplicate mutations: `0`.

Semantic reliability evidence included:

- `d2c-tr-std-refund-damaged`: `3/3 SUPPORTED → action → Risk-2 confirmation`;
- English valid refunds remained functional;
- Turkish multi-turn refunds remained functional;
- missing refund reasons continued to produce clarification rather than invention; and
- unsupported refund-reason provenance remained contained by the deterministic compiler.

The Turkish result is prospective evidence for this exact source, prompt, model, provider, and
contract binding; it is not a universal guarantee about future hosted-model behavior.

## D2d Operational Release Gate Evidence

M6.34 executed the approved source-bound operational gate:

| Field | Value |
| --- | --- |
| Experiment | `d2d_m6_34_release_gate_20260822T132645Z` |
| Source | `1c16e8d1f76ff184129385c3004bcb8737efb7af` |
| Contract | `d2d_release_candidate_operational_v1` |
| Contract SHA | `ebe77e28973a6314a3892ce896994c8e3897cd87ccf60e27ab5d1f1f8b8e0aa0` |
| Classification | `D2D_RELEASE_GATE_PASS` |
| Artifact schema | `d2d_release_candidate_artifact_v1` |

The frozen deployment was a single-environment Compose reference topology containing PostgreSQL,
Qdrant, deterministic bootstrap/ingestion, backend, frontend/operator console, and Jaeger/
OpenTelemetry. It used immutable image digests, isolated state, and the expected Alembic head
`20260812_0007`.

Operational validation passed:

- baseline deployed E2E: PASS;
- same-action concurrency: committed effects `1, 1, 1` across 16-way contention and 3 rounds;
- independent-action concurrency: committed effects `2, 2, 2` across 2 actions and 3 rounds;
- restart/persistence: PASS;
- fault matrix: `6/6` recovered;
- observability/privacy: PASS;
- mandatory phases: `8/8`;
- operational scenarios: `18/18`.

Safety and integrity invariants were all clean:

- duplicate mutations: `0`;
- unauthorized mutations: `0`;
- confirmation bypasses: `0`;
- stale resurrection: `0`;
- declined resurrection: `0`;
- unsafe executions: `0`;
- privacy violations: `0`;
- artifact/source/configuration drift: `0`.

This pass establishes the operational gate result for the frozen reference deployment. It does
not certify unrestricted production readiness, enterprise deployment, public-internet security,
capacity, disaster recovery, or regulatory compliance.

## Artifact Index

All listed artifacts were independently hash-verified. Paths are relative to the repository root.

| Milestone | Experiment | Artifact | SHA-256 |
| --- | --- | --- | --- |
| M6.29B | `d2c_m6_29_semantic_v3_20260822T011436Z` | `artifacts/live-eval/production-robustness/d2c_m6_29_semantic_v3_20260822T011436Z/attempts.json` | `4db17fde17cc97278f16df439361a5c7d30e66eb8f5528ba2f53ac40590cb627` |
| M6.29B | `d2c_m6_29_semantic_v3_20260822T011436Z` | `artifacts/live-eval/production-robustness/d2c_m6_29_semantic_v3_20260822T011436Z/manifest.json` | `24ad0fb0c2a9bd28056bb027516c68ecdcff030b3c1cc57e09b8955c2628c7b2` |
| M6.29B | `d2c_m6_29_semantic_v3_20260822T011436Z` | `artifacts/live-eval/production-robustness/d2c_m6_29_semantic_v3_20260822T011436Z/summary.json` | `6169745010cd67f578ff0fc7b67ce7f3c8703dfdb95e47ac14cf9ea691a281b3` |
| M6.29B | `d2c_m6_29_semantic_v3_20260822T011436Z` | `artifacts/live-eval/production-robustness/d2c_m6_29_semantic_v3_20260822T011436Z/summary.md` | `8c385d7a6ce31a33fe52f7356ad13e39f9a968219376bc28ee311f05096d8c1b` |
| M6.34 | `d2d_m6_34_release_gate_20260822T132645Z` | `artifacts/d2d/release-gates/d2d_m6_34_release_gate_20260822T132645Z/manifest.json` | `43ea5e51920b377b454b5a23df9abf8c045704cb1e67bd84c929b17f1ac6ad2a` |
| M6.34 | `d2d_m6_34_release_gate_20260822T132645Z` | `artifacts/d2d/release-gates/d2d_m6_34_release_gate_20260822T132645Z/environment.json` | `3acee850315b7e91b73731bbc8a3b6b78fc0e659b958a2f59baa1807c2f88e75` |
| M6.34 | `d2d_m6_34_release_gate_20260822T132645Z` | `artifacts/d2d/release-gates/d2d_m6_34_release_gate_20260822T132645Z/attempts.json` | `0495fcce816e0c7e7a79f93f1e9891046e8e631daf481abcd0373fcf41d8e734` |
| M6.34 | `d2d_m6_34_release_gate_20260822T132645Z` | `artifacts/d2d/release-gates/d2d_m6_34_release_gate_20260822T132645Z/summary.json` | `3fe9352786da02758dd6dacbea5911fbb25eec56d75dc981ac87eca37b257782` |
| M6.34 | `d2d_m6_34_release_gate_20260822T132645Z` | `artifacts/d2d/release-gates/d2d_m6_34_release_gate_20260822T132645Z/summary.md` | `656894a0da443c1607a97eb13bd8cb3d56151eb5b4e703160aace073d6b0fb41` |

## Release Status

- **D2c:** `CLOSED_FOR_CURRENT_RELEASE_CANDIDATE`
- **D2d:** `RELEASE_GATE_PASS`
- **Overall scope:** production-oriented reference validation, not unrestricted production
  certification.

The authoritative D2d contract remains [`docs/d2d-release-gate.md`](d2d-release-gate.md), and its
machine-readable source remains [`evaluation/d2d_spec.py`](../evaluation/d2d_spec.py). This
document indexes evidence; it does not replace those frozen contracts or alter their semantics.
