# Provider Outage Runbook

## Expected behavior

An LLM/provider outage is a degraded dependency, not automatic application
unavailability. The provider boundary must fail closed for actions. Recorded
replay or bounded uncertainty may remain available according to configuration;
no provider response can authorize a mutation.

## Investigation

1. Check `/health/details` and retry/circuit summaries.
2. Identify the bounded dependency category, timeout, retry budget, and circuit
   state.
3. Confirm no prompts, tokens, or provider payloads are present in telemetry.
4. Verify that pending confirmations, policy decisions, and idempotency state
   remain unchanged.

## Recovery

Resolve the provider/network issue, allow a controlled half-open probe, and
confirm circuit recovery. Do not increase retries beyond the configured budget
or route around deterministic validation.
