# Public showcase release notes

## Release posture

This repository presents a production-oriented reference implementation of an agentic customer
service platform. The release evidence covers a frozen semantic evaluation and a source-bound
operational reference deployment. It is not a claim of unrestricted production readiness,
enterprise deployment certification, capacity certification, or regulatory compliance.

## The project in one paragraph

Customer-service agents need to handle more than conversation. They must ground requests in
customer-scoped state, keep model output inside a deterministic authority boundary, persist
confirmation and action state, and leave evidence an operator can inspect. This platform makes
those boundaries visible in both the runtime architecture and the React Operator Console.

The central rule is:

> **The LLM proposes. Deterministic software decides what may execute.**

## Architecture

The request path is:

```text
User request
  -> Agent orchestration
  -> Semantic proposal
  -> Provenance validation
  -> Decision Compiler
  -> Policy evaluation
  -> Confirmation or escalation
  -> Execution authority
```

RAG, memory, and observability provide context or bounded evidence. They do not authorize a
business mutation. PostgreSQL holds durable state for checkpoints, confirmations, idempotency,
and business effects. Qdrant supports the retrieval path. OpenTelemetry and Jaeger expose bounded
operational stages without exposing raw prompts, provider responses, secrets, or hidden reasoning.

See the [architecture overview](architecture.md) for the diagram and trust boundaries.

## Showcase flow

The public demo is designed as a short investigation workflow:

1. **Overview:** start at `/overview` to see the platform boundary and the published release status.
2. **Playground:** choose a business or safety scenario, review the prefilled inputs, and submit it through the existing API.
3. **Investigation:** open the resulting run at `/runs/:runId` to follow the decision timeline, grounding evidence, policy outcome, confirmation state, and execution state.
4. **Safety evidence:** open the Safety view to connect the observed run to the D2c semantic/safety result and the D2d operational gate.

The UI is an operator and developer console. It does not provide policy overrides, confirmation
bypasses, direct tool execution controls, or hidden model reasoning.

For the visual tour, use the [README console walkthrough](../README.md#console-walkthrough).

## Validation evidence

### M6.29B D2c

The full prospective semantic and safety evaluation recorded:

- experiment: `d2c_m6_29_semantic_v3_20260822T011436Z`;
- measured attempts: `540/540`;
- deterministic gate: `110/110`;
- safety gate: `40/40`;
- resilience gate: `28/28`;
- unsafe semantic proposals: `30`;
- deterministic guard interventions: `30`;
- unsafe executable survivors: `0`;
- unsafe executions: `0`.

The historical executable-survivor trend is `15 -> 3 -> 0 -> 0 -> 0`. The critical Turkish
standard-refund positive control reached supported action and Risk 2 confirmation in `3/3`
repetitions. The result is evidence for the recorded source, prompt, model, provider, dataset,
and contract binding. It is not a universal claim about future model behavior.

### M6.34 D2d

The source-bound operational release gate recorded:

- experiment: `d2d_m6_34_release_gate_20260822T132645Z`;
- classification: `D2D_RELEASE_GATE_PASS`;
- mandatory phases: `8/8`;
- operational scenarios: `18/18`;
- fault classes recovered: `6/6`;
- same-action committed effects: `1, 1, 1`;
- independent-action committed effects: `2, 2, 2`.

The safety and integrity invariants were clean for the gate: zero duplicate mutations,
unauthorized mutations, confirmation bypasses, stale or declined resurrection, unsafe executions,
privacy violations, and source/configuration drift.

The [release evidence index](release-evidence.md) contains the artifact paths and SHA-256 values.
The [evaluation overview](evaluation-overview.md) explains the separation between D2c model and
safety validation and D2d operational validation. The [D2d contract](d2d-release-gate.md) defines
the operational acceptance criteria.

## Limitations

- The evidence covers the documented single-environment Compose reference deployment.
- Full application load and capacity characterization, longer soak tests, and stronger chaos exercises remain outside the validated release scope.
- Public-internet TLS, enterprise IAM, Kubernetes, multi-region operation, disaster recovery, autoscaling, and compliance certification are not established by these results.
- Live semantic evidence is identity-bound. The safety boundary contains unsupported proposals, but it does not prove that unseen model errors are impossible.
- Provider usage and cost telemetry are outside the D2d v1 release gate.

## Public repository metadata review

The repository name, `Agentic Customer Service Platform`, is descriptive and consistent with the
console and documentation. No remote GitHub metadata is changed by this document-only milestone.

Suggested GitHub description:

> Production-oriented agentic customer service platform with deterministic safety boundaries, provenance enforcement, and operational release validation.

Suggested topics:

`ai-agents`, `customer-service`, `agent-safety`, `llm-evaluation`, `rag`, `fastapi`, `react`,
`typescript`, `observability`

These are metadata recommendations for the public repository settings, not additional product or
evidence claims.
