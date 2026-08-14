# semantic_decision_v3 improvement plan

- Status: **PROPOSAL ONLY — NOT IMPLEMENTED**
- Milestone: M6.13
- Source analysis: M6.12 offline semantic failure analysis
- Source experiment: `d2c_m6_9_semantic_v3_20260813T233308Z`
- Source revision: `518fa11519a69e5bfcda12bf1f7b1492eac3f2f9`
- M6.11 audit SHA-256: `a496d0a3902e181ca45a78e4dedb4e2295db70d13a2564f0cf50d1e96dc8116c`
- M6.12 analysis SHA-256: `c36d1e58215e1c41cdde45de101ab34c4775823180572a5da15e769ddf95f6a7`

No model calls, D2c rerun, D2d execution, schema change, prompt change, contract change, or
runtime change is part of this milestone.

## Decision

Recommendation: **REQUIRE SEMANTIC_DECISION_V3 IMPROVEMENT FIRST**.

D2d must remain blocked until the proposal below is reviewed and, if accepted, implemented and
validated in a separately approved milestone. This document does not authorize implementation.

The plan deliberately preserves the `semantic_decision_v3` schema, function schema, contract
identity, grounding boundary, target admissibility boundary, compiler ownership, resolver
authority, policy, confirmation, replay, and exactly-once behavior.

## Evidence being addressed

M6.12 found 41 genuine model semantic failures and 18 genuine unsafe semantic proposals after
removing oracle/path mismatches from the routing denominator.

| Failure group | Count | Representative cases |
| --- | ---: | --- |
| Clarification/target/confirmation shape | 30 | `amb-order-status-no-id`, `amb-ticket-no-id`, `amb-contradictory-cancel`, `mt-decline-confirmation`, `mt-escalate-after-clarification` |
| Knowledge/action request-type mismatch | 4 | `std-refund-eligibility`, `std-cancellation-explanation` |
| Unsupported refund argument | 6 | `amb-refund-no-reason`, `adv-invent-refund-reason` |
| Ambiguous read route | 1 | `amb-latest-or-list` |
| **Total genuine semantic failures** | **41** | |

Unsafe proposals overlap the semantic failures:

| Unsafe group | Count | Representative cases |
| --- | ---: | --- |
| Destructive action despite required clarification | 12 | `amb-contradictory-cancel`, `mt-decline-confirmation` |
| Refund action with unsupported/invented reason | 6 | `amb-refund-no-reason`, `adv-invent-refund-reason` |
| **Total unsafe proposals** | **18** | |

Runtime safety remained clean in the source run: unsafe executions, confirmation bypasses,
unauthorized mutations, and duplicate mutations were all zero. The 18 proposals are nevertheless
semantic-boundary failures because an action proposal was produced when clarification was required.

## Minimal improvement proposal

### 1. Strengthen deterministic semantic guards first

The first implementation candidate should be evaluation-only and narrowly scoped to the existing
server-owned boundaries:

- Missing or ambiguous order/ticket references must remain clarification outcomes. A model-produced
  `latest_order` or concrete target must not turn an explicitly ambiguous request into an action.
- A destructive action in a multi-turn flow must require an authoritative pending confirmation
  state. A declined, stale, absent, or contradictory confirmation must compile to no action or
  clarification, never to a destructive action proposal.
- Refund `reason` must be accepted only when supported by the customer request and current turn
  state. The compiler must continue to reject absent, invented, or unsupported reasons without
  fabricating a business argument.
- Knowledge-and-action intents must preserve the expected request type and retrieval context.
  The deterministic path may derive fixed retrieval context, but it must not silently convert a
  semantically incomplete action into an unrelated route.

These guards must be expressed using existing deterministic inputs and existing result types. They
must not add fields to `semantic_decision_v3`, change function-calling schemas, or make the model
authoritative over confirmation or target state.

### 2. Consider a minimal prompt clarification only after guard design

If deterministic tests show that the model still emits the unsafe shapes, propose a narrow prompt
revision with four explicit rules:

1. For ambiguous destructive requests, emit clarification and do not select a concrete target.
2. For a declined or missing confirmation, do not propose the destructive action again.
3. Never invent a refund reason or other required business argument; request it from the user.
4. For refund eligibility and cancellation explanation, preserve the knowledge-and-action request
   type and the semantic target while leaving retrieval/action realization to the server.

This is a proposal only. Any prompt revision must preserve the contract and receive a new prompt
hash, a new approval, and a focused compatibility/regression validation before broader execution.

### 3. Add regression coverage before any new behavioral run

Add deterministic tests for:

- order lookup without an identifier: clarification, no resolver action;
- ticket lookup without an identifier: clarification, no resolver action;
- contradictory cancel language: clarification, no destructive proposal;
- confirmation declined, stale, or absent: no destructive proposal;
- escalation after clarification: required reason/state remains explicit;
- refund without reason: clarification;
- refund with model-invented reason: clarification;
- refund eligibility and cancellation explanation: action-capable knowledge route with fixed retrieval
  context;
- “recent orders” ambiguity: accepted list/latest behavior only when the case oracle allows it;
- EN/TR paired versions of every new case;
- repeated-turn variants proving pending-action authority and replay stability.

The tests must assert stage ownership separately: semantic decision shape, grounding, target
admissibility, compiler, resolver, policy, and confirmation. They must not use raw messages or
arguments in persisted audit artifacts.

## Expected impact

If the proposal works as intended:

- clarification correctness should improve for missing-target and multi-turn cases;
- unsafe proposal count should decrease from 18 without changing the zero unsafe-execution result;
- unsupported refund arguments should remain fail-closed;
- knowledge/action request-type mismatches should decrease without weakening retrieval or target
  authority;
- resolver correctness should remain stage-local and should not be “improved” by relabeling
  upstream semantic failures;
- no new schema or provider compatibility burden should be introduced.

No exact score uplift is promised. The next run must measure the unchanged denominators and report
both total routing and stage-conditional metrics.

## Validation strategy

Before any D2d consideration:

1. Implement only the approved minimal change in a separate milestone.
2. Run deterministic unit and integration tests for all listed cases.
3. Re-run the fixed semantic V3 compatibility gate if the prompt changes.
4. Preserve and hash all historical D2c/M6.10/M6.11/M6.12 artifacts.
5. Use a new approval and experiment identity for any prospective D2c validation.
6. Require zero unsafe executions, confirmation bypasses, unauthorized mutations, and duplicate
   mutations.
7. Compare semantic-failure and unsafe-proposal counts against the M6.10 baseline without changing
   the oracle after results are observed.

D2d may be reconsidered only after this validation demonstrates that the 41 semantic failures and
18 unsafe proposals have been materially reduced without a safety regression. No D2d execution is
authorized by this plan.

## Explicit non-goals

- No `semantic_decision_v4`.
- No schema or function-schema modification.
- No provider-specific contract or parser.
- No production default switch.
- No direct-tool architecture comparison.
- No dataset expansion in this milestone.
- No D2d or Live Eval v2 execution.
