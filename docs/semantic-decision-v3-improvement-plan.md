# semantic_decision_v3 improvement plan

- Status: **DETERMINISTIC CONTAINMENT IMPLEMENTED — PROSPECTIVE VALIDATION REQUIRED**
- Milestone: M6.13
- Source analysis: M6.12 offline semantic failure analysis
- Source experiment: `d2c_m6_9_semantic_v3_20260813T233308Z`
- Source revision: `518fa11519a69e5bfcda12bf1f7b1492eac3f2f9`
- M6.11 audit SHA-256: `a496d0a3902e181ca45a78e4dedb4e2295db70d13a2564f0cf50d1e96dc8116c`
- M6.12 analysis SHA-256: `c36d1e58215e1c41cdde45de101ab34c4775823180572a5da15e769ddf95f6a7`
- Follow-up: M6.23A attribution was inconclusive for `d2c-tr-std-refund-damaged` because the
  privacy-safe attempt projection omitted bounded semantic clarification and refund-reason state.
- M6.24 status: `semantic_attribution_observability_v1` implemented and offline-validated;
  prospective validation is still required.

The proposal below is retained as historical decision context. The narrow refund-reason
containment item is now implemented in `app/agent/decision_compiler.py` with focused deterministic
regression coverage. No model calls, D2c rerun, D2d execution, schema change, prompt change, or
contract change is part of this implementation milestone.

M6.24 is an attribution-only follow-up. It adds bounded fields derived from the parsed semantic
proposal and existing deterministic compiler result: model clarification intent, required refund
reason presence, support status (`MISSING`, `SUPPORTED`, `UNSUPPORTED`, `NOT_APPLICABLE`, or
`NOT_EVALUATED`), validation invocation, and a bounded compiler clarification cause. These fields
are emitted under `semantic_attribution_observability_v1`; historical attempts remain under
`containment_observability_v1` and are immutable. No prompt, provider contract, runtime decision,
scorer, oracle, dataset, or schedule semantics change.

## Decision

Historical recommendation: **REQUIRE SEMANTIC_DECISION_V3 IMPROVEMENT FIRST**.

D2d remains blocked until the implemented containment fix receives a new source-bound prospective
D2c validation. The historical proposal did not authorize the implementation; the current source
contains the separately scoped deterministic fix described below.

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

## Implemented release-hardening fix

The latest prospective M6.20B run left three executable survivors in the Turkish
`amb-refund-no-reason` repetitions. The compiler already checked refund-reason provenance, but it
accepted any single shared token after removing only English generic words. Turkish refund-action
terms such as `para iadesi` therefore counted as reason evidence.

The implemented compiler rule now fails closed unless authoritative user text is present and every
non-boilerplate token in the proposed reason is supported by that text. Bilingual refund, order,
request, and common function-word boilerplate is excluded from evidence. This keeps the model
proposal untrusted and does not change grounding, target admissibility, resolver, policy,
confirmation, idempotency, or replay authority.

Focused coverage proves Turkish and English missing/invented/lexically overlapping reasons clarify,
explicit Turkish and English reasons still compile to the normal Risk-2 path, and a confirmed
refund executes exactly once across replay. Existing grounding, admissibility, knowledge/action,
policy, confirmation, and idempotency suites remain separate stage-owned checks.

This is deterministic validation only. The historical M6.20B result remains unchanged; a new
prospective D2c run is still required before the P0 blocker can be considered closed for release.

M6.23A showed that the M6.22B Turkish valid-refund positive-control clarification could not be
attributed from the existing privacy-safe evidence. M6.24's offline fixtures distinguish model
clarification from missing, supported, and unsupported refund reasons, including compiler
provenance rejection, without retaining raw text or identifiers. This does not prove model
semantic variance or a runtime regression; a future source-bound prospective run is required if
the case must be conclusively attributed.

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

This prompt option remains historical proposal text and is not part of the implemented fix. Any
future prompt revision must preserve the contract and receive a new prompt hash, a new approval,
and focused compatibility/regression validation before broader execution.

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

1. The approved minimal deterministic change is implemented in a separate release-hardening
   milestone.
2. Run deterministic unit and integration tests for all listed cases.
3. Re-run the fixed semantic V3 compatibility gate if the prompt changes.
4. Preserve and hash all historical D2c/M6.10/M6.11/M6.12 artifacts.
5. Use a new approval and experiment identity for any prospective D2c validation.
6. Require zero unsafe executions, confirmation bypasses, unauthorized mutations, and duplicate
   mutations.
7. Compare semantic-failure and unsafe-proposal counts against the M6.10 baseline without changing
   the oracle after results are observed.

D2d may be reconsidered only after a new prospective validation demonstrates zero unsafe executable
survivors and no safety regression. No D2d execution is authorized by this plan.

## Explicit non-goals

- No `semantic_decision_v4`.
- No schema or function-schema modification.
- No provider-specific contract or parser.
- No production default switch.
- No direct-tool architecture comparison.
- No dataset expansion in this milestone.
- No D2d or Live Eval v2 execution.
