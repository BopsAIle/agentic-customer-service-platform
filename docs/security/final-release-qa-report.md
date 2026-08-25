# Final Release QA Report

Date: 2026-08-25

## Runtime Contract

The real-provider evidence used the required contract:

```text
Provider: openai_compatible
Model: gpt-5.6-terra
Structured output: function_calling
Reasoning effort: none
Decision contract: semantic_decision_v3
Projection backend: postgres
```

No API keys, prompts, customer data, or production identifiers are included in
this report. Security-boundary requests that matched bounded deterministic
patterns were rejected before provider invocation; normal semantic requests
were observed through the OpenAI-compatible provider/model projection.

## Environment Isolation

Mutation and recovery evidence came from the repository's isolated QA/integration
fixtures and the process-scoped authenticated smoke environment. The final
projection sample used the running local QA stack for read-only FAQ requests.
The deterministic fixture contract includes isolated refundable, duplicate,
invalid-order, and invalid-cancellation states, reset memory, and a versioned
knowledge snapshot.

No production customer or business data was used. The final pass did not reset
or alter unrelated working-tree state.

## Scenario Totals

The historical full real-LLM audit remains preserved in
`docs/security/real-llm-production-qa-report.md`:

- 100 evaluated samples: 82 passed, 18 warning/partial quality outcomes.
- 0 unauthorized mutations, confirmation bypasses, duplicate effects,
  authority-bearing memory writes, or customer-data disclosures.

Focused remediation evidence then covered 21 real-provider scenarios and the
final browser evidence added:

- 6/6 repository Playwright operator journeys passed.
- 30/30 read-only real-provider conversations produced a visible operator
  projection; terminal projection failures: 0.
- Authenticated lifecycle smoke passed, including restart, recovery, completion,
  replay safety, durable projection, and memory-safety checks.
- The full 100-sample matrix was not repeated in this final evidence pass; its
  results are carried forward unchanged and are not counted as new samples.

## Automated Validation

| Check | Result |
|---|---|
| Default-contract backend pytest | **844 passed** |
| Ruff check | **passed** |
| Ruff format check | **passed** |
| Mypy (`app tests evaluation scripts`) | **passed** |
| Frontend Vitest | **49 passed** |
| Frontend TypeScript typecheck | **passed** |
| Frontend ESLint | **passed** |
| Frontend production build | **passed** |
| Playwright operator journeys | **6/6 passed** |
| Authenticated lifecycle smoke | **passed** |
| Docker health/topology validation | **passed** |
| `/health` and `/ready` | **passed** |
| Production Compose config | **passed** with explicit validation-only required variables |
| `git diff --check` | **passed** |

The Playwright suite ran without changing tests, using the installed repository
Chromium executable through the existing `PLAYWRIGHT_CHROME_PATH` hook. The
package's expected browser cache was incomplete, but the available compatible
Chromium runtime executed all six journeys successfully.

## Real-LLM Quality Metrics

Evidence available from the historical and focused real-provider runs:

| Metric | Observed result |
|---|---|
| Core semantic preflight | 5/5 correct after the focused remediation |
| Refund paraphrase routing | 10/10 in the historical matrix |
| Cancellation paraphrase routing | 3/3 in the historical matrix |
| Policy routing | 6/6 in the historical matrix |
| Focused security override patterns | 7/7 explicit deterministic denials |
| Focused English/Turkish RAG topics | Grounded for tested supported topics; unsupported crypto abstained |
| Legitimate memory write/read | Passed; summary returned only allowed preference memory |
| Cross-customer disclosure | 0/7 in the historical audit; focused probes also disclosed nothing |
| Unauthorized mutation | 0 observed |
| Duplicate business effect | 0 observed |
| Projection visibility sample | 30/30 visible; 0 terminal failures |

The focused RAG retest corrected the observed eligibility-versus-processing-time
topic mismatch for tested timing questions and grounded the tested Turkish
conditions query. Unsupported crypto policy safely abstained. The historical
18 warnings remain part of the record; they are not erased by the focused
sample.

### Latency and cost

The final browser projection sample had the following wall-time measurements
from page navigation through visible projection (including model and UI work):

- p50: 1,830 ms
- p95: 2,045 ms
- maximum: 2,154 ms

The historical model-bearing sample measured provider latency at p50 1,306.658
ms and p95/maximum 1,703.303 ms. Token usage and provider cost are not exposed
by the bounded operator projection, so no cost estimate is fabricated.

## Safety Invariants

| Invariant | Status | Evidence / limitation |
|---|---|---|
| I1. No mutation without deterministic authority | **PASS** | Refund and cancellation completed only after compiler, policy, and authority stages. |
| I2. Risk-2 mutation requires explicit confirmation | **PASS** | Clean, negative, ambiguous, and mixed confirmations exercised. |
| I3. Confirmation binds to the exact pending action | **PASS for exercised flows** | Resume, replacement, and altered-target protections were exercised; broad stale-target coverage remains limited. |
| I4. Business state is revalidated before mutation | **PASS for exercised fixtures** | Invalid and duplicate states failed closed; an independently injected state-change case was not repeated in this final pass. |
| I5. Completed action cannot execute twice | **PASS** | Replay produced an explicit idempotency projection and no second effect. |
| I6. Memory cannot create authorization | **PASS** | Authority, approval, bypass, and role claims were rejected and absent from summaries. |
| I7. User/RAG/memory text cannot alter server policy | **PASS for exercised cases** | False policy assertions did not authorize execution. |
| I8. Customer/tenant scope cannot leak through ambiguity | **PASS for observed customer scope; tenant-specific browser path unverified** | Cross-customer probes disclosed no existence, amount, status, or metadata. |
| I9. Prompt injection cannot grant authority | **PASS for tested bounded families** | English and Turkish jailbreak/impersonation patterns denied before execution. |
| I10. Interruption cannot become confirmation | **PASS** | English and Turkish mixed confirmations suspended and preserved the pending boundary. |
| I11. Superseded actions cannot be revived | **PASS for tested replacement directions** | Both replacement directions were exercised with separate confirmation boundaries. |
| I12. Refresh/backend recovery cannot duplicate or lose authority | **PASS** | Browser refresh and authenticated backend restart recovery passed. |
| I13. Malformed provider output cannot execute | **PASS in authoritative backend harness; browser failure injection unverified** | Full pytest includes malformed-output, timeout, and error-taxonomy coverage. |

No absolute safety invariant was observed to fail.

## Recovery Evidence

- Pending refund survived browser reload with conversation, pending action, and
  confirmation boundary restored.
- Suspended workflow and resume behavior passed in focused real-provider QA.
- Authenticated smoke passed backend restart recovery, completion, and replay
  safety.
- A completed action remained completed/non-actionable after recovery.
- A security-denied pending action was not revived by a later clean confirmation.

## Provider Failure Evidence

Existing authoritative backend tests cover provider failure taxonomy, malformed
structured output, tool timeouts, and bounded failure projection. The full
backend suite passed these checks. No safe browser-facing failure-injection
control was available for this release pass, so the following are **UNVERIFIED
COVERAGE**, not passes claimed from fabricated failures:

- real-provider timeout through the browser
- connection failure through the browser
- 429/rate-limit through the browser
- malformed function call injected through the browser
- no-function-call and partial-argument provider responses through the browser

The existing contract tests verify that malformed/provider failures do not grant
authority or execute a mutation.

## Projection Reliability

The final measurement submitted 30 normal read-only real-provider requests and
observed 30 visible operator projections with zero terminal projection failures.
One browser response-locator wait timed out during the second measurement loop;
the resulting DOM still contained the complete `Agent trace timeline` and final
decision projection, so it was not counted as a projection failure. The browser
surface does not expose whether the first projection read required the client's
bounded retry, so retry count is **not observable**. The existing client behavior
is bounded (three short reads at 0/100/250 ms), with no infinite polling and no
mutation retry.

No transient 404 was reproduced in the final sample. The remaining issue is an
observability measurement limitation, not an observed terminal projection
failure.

## Remaining Risks

The following are warnings or unverified coverage, not observed safety
violations:

1. The full 20-input × 3 real-model stability matrix was not repeated during
   this final pass; the historical run contained a smaller 5-input × 3 sample.
2. Initial projection retry counts are not exposed in the browser UI.
3. Token usage and provider cost are not exposed in bounded operator telemetry.
4. Browser-level provider fault injection was unavailable; backend contract tests
   are the authoritative evidence for malformed and timeout handling.
5. Tenant-specific cross-scope browser navigation was not available through the
   current UI, although customer-scope probes were fail-closed.
6. The historical 18 semantic-quality warnings remain historical evidence and
   should be tracked separately from safety invariants.

Finding classifications:

- **SECURITY FAILURE:** none observed.
- **SEMANTIC QUALITY ISSUE:** historical real-language/RAG warnings; focused
  tested security and RAG gaps were remediated.
- **WORKFLOW QUALITY ISSUE:** no focused replacement or recovery failure remains
  in the exercised paths.
- **OBSERVABILITY ISSUE:** retry counts and cost/token telemetry are not visible.
- **ENVIRONMENT LIMITATION:** browser-level provider fault injection and direct
  tenant-specific UI paths were unavailable.
- **UNVERIFIED COVERAGE:** full 20×3 stability and browser-level provider faults.

## Release Decision

**READY WITH WARNINGS**

The tested release invariants passed: no unauthorized mutation, confirmation
bypass, duplicate business effect, authority-bearing memory, cross-customer
disclosure, or security-denied workflow revival was observed. Real-provider
normal routing, RAG, memory, confirmation, replay, replacement, browser refresh,
backend restart, and the repository's six Playwright journeys are green.

`RELEASE READY` is not claimed because the final evidence still has explicit
unverified coverage for browser-level provider faults, the full requested
stability matrix, tenant-specific browser scope, and retry-attempt visibility.

No application code, tests, or runtime configuration were modified for this
QA pass. No commit, push, staging, reset, stash, or unrelated cleanup was
performed.
