# D2b semantic behavioral evaluation specification

- Status: **PREPARED — NOT APPROVED FOR EXECUTION**
- Spec: `d2b_semantic_behavioral_matrix_v1`
- Approval gate: `d2b_review_approval_gate_v1`
- D2a decision: `model_compatibility_d2a_v1`
- Initial eligible set: `gpt-5.6-luna`

D2b evaluates model/runtime behavior while holding the accepted semantic architecture fixed. It is
not another architecture comparison: `direct_tool_v1` is not an arm. The pipeline remains LLM →
`semantic_decision_v3` → grounding → target admissibility → deterministic compiler → permitted
business resolution → validation → policy/confirmation → execution.

The frozen dataset strategy is `live_eval_v1_2`, 28 cases (14 EN and 14 TR), three repetitions,
and 84 measured attempts per eligible model. At most one unscored warmup is allowed. The case order,
prompt, schema, function-calling mode, reasoning setting, temperature, 30-second timeout, and zero
retry policy are fixed. Candidate-specific contracts or prompts are forbidden.

The scorer reports routing correctness over total and scorable attempts; semantic target
correctness; appropriate, missed, and unnecessary clarification; unsafe proposals separately from
unsafe execution; hallucinated identifiers; stage-local compiler and resolver correctness; exact
and semantic consistency; provider/end-to-end latency; and provider token usage when available.
Cost remains unavailable unless supplied by existing provider metadata and is never inferred from a
hard-coded price table.

Canonical artifacts require immutable source identities and hashes, exact model/runtime and run
metadata, bounded failure taxonomy, atomic COMPLETE publication, SHA-256 recording and post-test
hash verification. They must not contain credentials, authorization headers, raw provider payloads,
function arguments, prompts, hidden reasoning, real customer data, memory, RAG content, or
production data.

## Execution gate

No D2b runner may start model generation until a separate review supplies a matching explicit
`D2bReviewApproval`. Missing or mismatched approval fails closed with
`D2B_REVIEW_APPROVAL_REQUIRED` or `D2B_REVIEW_APPROVAL_MISMATCH`. Preparing this specification does
not constitute approval. This milestone performs no model call, live evaluation, artifact
generation, production-default change, or schema/prompt change.
