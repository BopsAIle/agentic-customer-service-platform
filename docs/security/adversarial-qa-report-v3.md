# Adversarial Security QA Report v3

Date: 2026-08-25

## Scope

This release-hardening pass addresses the previous adversarial review of memory
poisoning, prompt injection, workflow interruption, confirmation safety, RAG
relevance, and authorization boundaries. The changes are limited to deterministic
classification, read-only projection, and customer-facing messaging. Business
execution authority, policy evaluation, confirmation requirements, and mutation
behavior are unchanged.

## Findings before fixes

| Area | Risk | Severity | Status |
| --- | --- | --- | --- |
| Memory authority claims | Authority claims could be classified too broadly as ordinary memory or receive a generic signal. | Critical | Fixed |
| Validation-bypass memory | “No longer needs verification” wording could be persisted as customer context. | Critical | Fixed |
| Pending workflow interruption | A suspended mutation was safe but the customer response did not clearly explain that confirmation was still required. | High | Fixed |
| Memory summary routing | Read-only memory summaries were not explicitly distinguished from ordinary clarification. | Medium | Fixed in the local workflow projection |

## Fixes applied

- Added deterministic memory security patterns for confirmation, validation,
  approval, authorization, and policy bypass claims.
- Applied specific override classification before generic authority-claim
  classification. The bounded signal is
  `memory_security_override_attempt`.
- Kept rejected memory out of persistence and out of future retrieval. Rejected
  security metadata is not included in customer memory summaries.
- Added an explicit read-only memory-summary path using the existing frozen
  semantic contract, without changing historical transport schemas.
- Added customer-facing messaging that explains a suspended request remains saved,
  was not confirmed or executed, and can be continued later.

## Security guarantees

- LLM output cannot grant execution authority.
- Memory cannot create permissions, roles, approvals, or verification bypasses.
- Confirmation remains a deterministic boundary for sensitive mutations.
- Security and memory policy rejection remains fail-closed.
- Customer responses do not expose policy hashes, internal identifiers, raw policy
  inputs, secrets, or hidden reasoning.

## Validation

| Check | Result |
| --- | --- |
| Targeted memory, agent, compiler, and workflow tests | Passed |
| Full backend pytest suite | Passed |
| Ruff check | Passed |
| Ruff format check | Passed |
| Mypy (`app tests evaluation scripts`) | Passed |
| Frontend tests | Passed — 48 tests |
| Frontend typecheck, lint, and build | Passed |
| Playwright operator journeys | Passed — 6/6 journeys |
| Authenticated lifecycle smoke | Passed — confirmation, restart, replay, projection, audit, and memory checks |

## Remaining limitations

The memory-summary operation retains the existing frozen semantic transport enum
for compatibility with historical evaluation identities; its read-only intent is
carried by the explicit workflow state and decision reason. This avoids changing
or rewriting frozen evaluation evidence.
