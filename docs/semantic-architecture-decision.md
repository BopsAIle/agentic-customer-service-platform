# Semantic decision architecture

- Status: **ACCEPTED**
- Decision date: 2026-08-13
- Scope: canonical semantic architecture for subsequent model/runtime evaluation
- Source experiment: `architecture_ab_luna_v3_20260813T170212Z`
- Corrected scorer: `architecture_ab_scoring_v2_1`
- Corrected dataset: `live_eval_v1_2`
- Dataset hash: `d8a10741dbb90e8a4de3b09098de36c4969c0b72944d253e37c9580279064eb5`

## Decision

The canonical semantic architecture for subsequent model/runtime evaluation is:

```text
LLM
→ semantic_decision_v3
→ semantic entity grounding
→ target admissibility
→ deterministic DecisionCompiler
→ BusinessTargetResolver where permitted
→ business validation
→ policy and confirmation
→ execution
```

The model interprets the request and produces a semantic decision. It does not authoritatively
select executable tools, customer scope, trusted identifiers, policy outcomes, or confirmation
state. Grounding, destructive symbolic-target restrictions, customer-scoped resolution, business
validation, policy, replay, and exactly-once controls remain server-owned.

This is an evaluation/reference-architecture decision, not a production adoption decision.
`direct_tool_v1` remains the current runtime default. No provider or hosted-model default changes
with this decision; a future release/adoption milestone must evaluate any default switch separately.

## Evidence

D1b compared `direct_tool_v1` with `semantic_decision_v3` using the same `gpt-5.6-luna` model,
official OpenAI API provider, configuration, `live_eval_v1_1` cases, counterbalanced schedule, and
three repetitions per case. Each arm had 84 measured attempts. The corrected offline rescore used
the immutable model outputs from source revision
`5c19188771b189af25701ff4eaef461f19ddd390`; it made no API or model calls.

The immutable source artifacts are `direct_tool_v1.json`
(`84581e128381d57fdc87bf7c5ae74cefc3658e3da40ae2103a35830ea66f9d3d`),
`semantic_decision_v3.json`
(`b7cd24a7338c92cba478a123666c5772cae0a797da8bfbfc5127275977a96c0d`), and the original
comparison JSON/Markdown
(`638634a4263119656d7cfc667fbcf53a6f90b3ac425d73b5bd8381f556ef7e7d` /
`909b2b1a76f9a1ad662e597c5edd572d3a22c29060cd3562374e1762a57cc0bc`).

| Measure | Direct | Semantic V3 |
| --- | ---: | ---: |
| Routing | 69/84 (82.14%) | 79/84 (94.05%) |
| Effective clarification | 69/84 (82.14%) | 79/84 (94.05%) |
| Pre-policy unsafe proposals | 3/84 | 1/84 |
| Hallucinated identifiers | 0/84 | 0/84 |
| Case-level wins | 1 | 6 |

Twenty-one cases were tied. Semantic V3 improved routing and effective clarification by 10 attempts,
or 11.90 percentage points. Its deterministic compiler was correct in 84/84 attempts and 71/71
when conditioned on correct model semantics. `BusinessTargetResolver` was correct in 50/50 eligible
attempts and 50/50 given a correct reference.

Layer B remained clean for both arms: zero unsafe executions, confirmation bypasses, unauthorized
mutations, and duplicate mutations. Grounded explicit cancellation confirmation/replay passed;
ungrounded concrete targets and destructive symbolic targets were blocked; a user-supplied fake
integer ID was grounded but rejected by business validation. Pre-policy proposal counts are not
unsafe-execution counts.

Canonical mean end-to-end latency was 1688.31 ms for direct and 1665.49 ms for semantic. This is
not evidence that semantic is faster: provider-call variation drove the observed total difference.
Semantic deterministic post-provider processing added approximately 0.29 ms.

## Evaluation correction disclosure

The original `architecture_ab_scoring_v2` result was a 72/84 versus 72/84 tie, classified `MIXED`.
The D1b.1 audit found three deterministic evaluation defects and introduced the explicit successor
`architecture_ab_scoring_v2_1`:

1. A latest-order task required the direct arm's `get_customer_orders` tool from both architectures.
   The corrected scorer accepts task-equivalent realizations: direct list retrieval, or semantic
   `ORDER_LOOKUP + latest_order` followed by customer-scoped resolution and `get_order`.
2. Two correct resolver outcomes were attributed as failures because the compiler subsequently
   requested a missing refund reason. Resolver correctness is now stage-local.
3. `en-refund-short` provided an order ID but no reason even though the product refund contract
   requires a non-empty reason. The narrow `live_eval_v1_2` oracle expects clarification/no action;
   it does not reward a model-invented business argument.

No model output, prompt, semantic contract, product behavior, or source D1b artifact changed. The
correction was offline-only and did not regenerate either arm. Historical
`architecture_ab_scoring_v2` and `live_eval_v1_1` remain interpretable and immutable.

## Evidence chain

- D1 with Qwen/V2 exposed concrete-target authority, destructive symbolic-target authority, and
  structured-output compatibility issues.
- M5.4c.1 added concrete semantic identifier grounding.
- M5.4c.2 restricted destructive symbolic targets.
- M5.4c.3/c.3a/c.3b added structured-output diagnostics, a hosted control, and residual-target
  attribution.
- M5.4c.4 introduced `semantic_decision_v3` and production-ID-aligned evaluation data.
- M5.4c.4a found low Qwen/Ollama and high Luna compatibility with the same V3 contract.
- D1b performed the clean same-model architecture comparison.
- D1b.1 corrected deterministic evaluation semantics and rescored the frozen outputs offline.

Qwen3.5 4B/Ollama produced 3/24 typed V3 decisions under the canonical `function_calling`
compatibility gate, while Luna produced 24/24. This is a model/runtime structured-contract
compatibility result, not an architecture blocker or a general claim about Qwen model quality.

## Why no D1c

D1c is not required because the canonical outputs were valid, the defects and corrections were
deterministic, no model regeneration was needed, corrected routing materially separated the arms,
case-level results favored semantic six to one with 21 ties, and runtime safety stayed clean. A new
architecture experiment would be warranted only if future evidence invalidates these premises.

## Limitations

- The evaluation contains 28 synthetic cases with three repetitions each.
- The canonical A/B used one hosted control model.
- EN/TR evidence is useful but small.
- Architecture selection does not establish universal model/runtime compatibility.
- It does not approve a production contract or provider-default change.
- A model/runtime matrix remains necessary.

## D2 entry condition

D2 must hold the architecture fixed at `semantic_decision_v3` and ask: which candidate
model/runtime can satisfy this structured contract reliably enough to operate the selected
deterministic architecture within the current runtime budget?

Candidates should first pass a structured-contract compatibility gate. Only eligible candidates
should proceed to the behavioral model matrix. Models must not receive different semantic contract
versions merely to improve their scores; this preserves the separation between architecture and
model/runtime effects.
