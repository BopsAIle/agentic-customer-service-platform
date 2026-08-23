# Distributed reliability boundaries

The runtime isolates dependency uncertainty from decision and execution authority. Reliability
controls may delay, reject, or degrade dependency work; they cannot approve a tool, satisfy a
confirmation, alter policy, or create an execution identity.

## Retry safety

The system retries uncertainty only when replay safety is guaranteed. Read-only provider,
retrieval, and tool operations may use bounded exponential backoff with jitter. A retry sequence is
limited by:

- a maximum attempt count;
- a per-service retry budget over a bounded window;
- the request deadline and the dependency's native timeout;
- a capped `Retry-After` value when a dependency supplies one; and
- the dependency circuit and bulkhead state.

Application retries begin only after the prior native dependency call has returned. Provider SDK
retries remain disabled so there is one visible retry authority.

Writes are not automatically retried. In particular, `UnknownWriteOutcomeError` is terminal for
the request: the runtime records the uncertain outcome and does not replay the mutation.
Reconciliation continues to use the original server-owned idempotency identity.

## Circuit breaker

Each application replica tracks a circuit by bounded service identity. Circuits move through:

- **closed**: calls are admitted and retryable dependency failures are counted;
- **open**: calls fail closed without contacting the dependency; and
- **half-open**: a bounded number of recovery probes may run after the recovery interval.

A successful half-open probe closes the circuit. A failed probe opens it again. Circuit state does
not grant execution authority and is intentionally not persisted as business state.

## Bulkhead isolation

Per-service semaphores bound simultaneous dependency calls. Model-provider capacity is isolated
from retrieval, memory, and tool capacity, so a slow dependency cannot consume every worker slot.
When a bulkhead is full, new work is rejected immediately or after the configured bounded wait;
the runtime then follows its existing safe degraded/error path.

## Rate limiting

The runtime applies bounded sliding-window limits to:

- authenticated principals;
- server-resolved customer scopes; and
- actual model-provider call attempts.

Principal and customer keys are hashed in limiter state. Metrics contain only the limit scope, not
identity values. Limits in this implementation are per application replica. A multi-replica
deployment that requires a strict global quota must also use a trusted gateway or shared limiter;
that external layer must not replace `resolve_customer_scope()` or any application authorization
check.

## Observability and privacy

Bounded metrics cover retry attempts and exhaustion, circuit opening and recovery, and rate-limit
rejections. Trace attributes use internal dependency/service categories only. Reliability
telemetry never includes prompts, user messages, provider tokens, authorization headers,
credentials, raw model output, or customer content.

## Configuration

All controls use `RESILIENCE_*` settings. Local defaults are conservative and may be adjusted per
deployment after capacity testing. Changing a retry count does not make writes replay-safe:
operation classification and unknown-write handling remain authoritative.

The reliability layer is deliberately separate from:

- the Decision Compiler;
- policy evaluation;
- confirmation and revalidation;
- idempotency;
- tool validation; and
- controlled execution authority.
