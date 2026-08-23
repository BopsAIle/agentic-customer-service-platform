# Demonstration Scenarios

These walkthroughs describe the observable control-plane path. They are scenario inputs and
expected boundaries, not fabricated execution results.

## Refund request with memory + RAG

**Flow:** Request → Context → Proposal → Decision → Evidence

**Evidence:** Bounded customer context and refund-policy retrieval support the proposal.

**Expected:** The refund proposal is validated and confirmation requirements are enforced before
execution. The authority boundary remains active until confirmation.

## Prompt injection attempt

**Expected:** Untrusted instructions remain contained. The model cannot bypass policy or gain
execution authority.

## Duplicate operation protection

**Expected:** A repeated refund request is checked against the existing operation and prevented
from creating a duplicate business effect.

## Missing information clarification

**Expected:** A refund request without sufficient target information requires clarification. The
system does not guess and execution is not attempted.

The [Operator Console](../README.md#production-showcase) can be used to submit supported local
scenarios and inspect whatever bounded projection the backend returns. Unavailable fields remain
explicitly unavailable.

## Live proposal mode

The Playground also exposes an explicit **Live proposal run** mode. When the server is configured
with the OpenAI API, the provider contributes a structured semantic proposal only: intent, a
bounded suggested action, and typed target fields. The existing grounding, compiler, target
validation, policy, confirmation, and execution-authority layers still decide what may proceed.

If the server has no OpenAI key or is not pointed at `https://api.openai.com/v1`, the request stays
on the recorded evidence path and the UI reports: **Live model unavailable. Showing bounded evidence
replay.** Provider credentials and raw model responses are never projected to the console.
