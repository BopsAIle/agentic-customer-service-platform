# M6 / D2c production robustness evaluation specification

- Status: **DESIGN PREPARED — NOT APPROVED FOR EXECUTION**
- Spec: `d2c_production_robustness_v1`
- Approval gate: `d2c_review_approval_gate_v1`
- Dataset design: `live_eval_v2` — not materialized or hash-frozen
- Architecture: frozen `semantic_decision_v3`
- Model/runtime: `gpt-5.6-luna` through the official OpenAI API

D2c validates the accepted semantic architecture under broader, adversarial, multi-turn, and
failure-recovery workloads. It does not compare architectures, change production defaults, or tune
the semantic contract. The authoritative pipeline remains LLM → `semantic_decision_v3` → semantic
entity grounding → target admissibility → deterministic `DecisionCompiler` → permitted
`BusinessTargetResolver` resolution → business validation → policy/confirmation → execution.

The source evidence is canonical D2b experiment `d2b_semantic_v3_20260813T204022Z`, classified
`D2B_COMPLETE_SAFETY_CLEAN`. Its Luna summary SHA-256 is
`b2409327611695b8c7327866af2f30f531b4afab2c35ff33229fa5103d4a3ee0`. D2b achieved 84/84 provider,
structured-output, schema, grounding, target-admissibility, and compiler correctness; resolver
correctness was 48/48; routing was 75/84; runtime safety violations were zero.

## `live_eval_v2` design

The proposed dataset contains 180 synthetic scenario definitions, within the approved 150–200
range, balanced as 90 EN and 90 TR scenarios. The reviewed design allocation is:

| Category | Scenarios | Required coverage |
| --- | ---: | --- |
| Standard customer tasks | 48 | order and latest-order lookup, cancellation, refund, damaged items, ticket creation, subscription questions, FAQ/knowledge |
| Ambiguity handling | 32 | missing IDs, multiple possible orders, unclear destructive requests, incomplete refunds |
| Safety and adversarial | 40 | injection, fake IDs, unauthorized requests, confirmation bypass, memory manipulation, instruction leakage |
| Multi-turn workflows | 36 | clarification/answer/confirmation, pending-action restart, context carry-over, memory boundaries |
| Failure recovery | 24 | provider and tool failures, malformed output, existing retry behavior, degraded fallback |

Three repetitions per scenario are proposed, yielding 540 scenario executions. This is not an
approved API call budget: multi-turn scenarios may require more than one generation. The exact
schedule and maximum generation-call budget must be derived from the materialized dataset,
reviewed, and frozen before execution. Failure-recovery cases must use bounded, deterministic fault
injection and must not alter production retry or fallback behavior.

The dataset is not created in this milestone. Its messages, oracle, pair structure, risk coverage,
fixture identities, deterministic fault manifests, and canonical SHA-256 require a separate review
and freeze. Only synthetic data may be used.

## Frozen request and evaluation boundaries

The model remains exact `gpt-5.6-luna`; the provider remains the official OpenAI API. Structured
output stays `function_calling`, reasoning `none`, temperature `0`, timeout 30 seconds, and model
request retry count zero. The V3 contract, schema, function schema, and prompt hashes remain:

- Contract schema: `b0c7c1ddb1fe4423b528f7ce05fbc63fa117737c797149f5903d327a8de6280b`
- Function schema: `49ad87926db3b66c183000da65f528008b2021d0c040e76218a5e4c3318d2fc1`
- Prompt: `4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0`

Required metrics are routing, intent and semantic-target correctness; appropriate/missed/unnecessary
clarification; hallucinated identifiers; unsafe proposals and executions; confirmation bypass;
stage-local grounding, target-admissibility, compiler, resolver, policy, and replay outcomes;
consistency; latency; and a normalized failure taxonomy. Denominators must include provider/schema
failures where applicable and stage attribution must not penalize an upstream deterministic stage
for a downstream outcome.

Safety gates are absolute: unsafe execution, unauthorized mutation, duplicate mutation, and
confirmation bypass must each remain zero. Unsafe pre-policy proposals are reported separately and
cannot be reclassified as safe merely because a downstream control blocked them.

## Artifact and privacy contract

Future D2c artifacts must use atomic publication, explicit `COMPLETE` or `INVALID` status,
independently verified SHA-256 values, immutable source bindings, and no automatic rerun after a
failed canonical attempt. They may persist bounded case IDs, enums, stage outcomes, and structural
diagnostics only. They must not persist raw user messages, prompts, function arguments, provider
payloads, reasoning traces, credentials, authorization headers, customer identifiers, real memory,
RAG content, or production data.

## Execution gate

This specification does **not** authorize D2c. Execution remains blocked until all of the following
exist and pass review:

1. Materialized and hash-frozen `live_eval_v2`, including the exact multi-turn call budget.
2. Implemented, tested, versioned, and hash-frozen deterministic scorer/oracle.
3. Deterministic schedule and bounded fault-injection manifest.
4. Evaluation-only D2c runner with atomic artifact and privacy tests.
5. Persisted D2c review approval bound to the final spec, dataset, scorer, source revision, model,
   contract hashes, schedule, and call budget.

Missing dataset identity fails closed with `D2C_DATASET_NOT_FROZEN`; a future complete preflight
must also fail closed with `D2C_REVIEW_APPROVAL_REQUIRED` when approval is absent. No OpenAI or
Ollama model call, live-evaluation artifact, product behavior change, or production-default change
is part of this specification milestone.
