# Evaluation Overview

The release candidate uses two complementary gates. D2c evaluates semantic/model behavior and
deterministic safety boundaries; D2d evaluates whether the validated application operates
correctly as a production-oriented reference deployment.

## D2c — Semantic and Safety Validation

D2c validates:

- semantic correctness across frozen multilingual and multi-turn scenarios;
- model proposal structure and routing diagnostics;
- semantic provenance behavior;
- deterministic grounding, target admissibility, compilation, policy, confirmation, and
  containment boundaries; and
- unsafe executable survivors and unsafe executions.

The current full prospective result is M6.29B: `540/540` measured attempts, zero unsafe
executable survivors, zero unsafe executions, and a `3/3` supported Turkish standard-refund
positive control reaching Risk-2 confirmation. See [`docs/release-evidence.md`](release-evidence.md)
for the immutable artifact index.

## D2d — Operational Release-Gate Validation

D2d does not repeat the model-quality benchmark. It validates:

- clean deployment and migration correctness;
- health/readiness and baseline end-to-end operation;
- same-action concurrency and idempotency;
- persistence across restart, replay, decline, and stale-confirmation paths;
- selected dependency failure and recovery behavior; and
- deployed observability and privacy-safe evidence.

M6.34 passed the source-bound operational gate with `18/18` scenarios, `8/8` phases, `6/6` fault
classes, same-action effects `1, 1, 1`, independent-action effects `2, 2, 2`, and zero privacy
violations.

The authoritative D2d contract is [`docs/d2d-release-gate.md`](d2d-release-gate.md). A gate pass
means the frozen production-oriented reference deployment passed its defined operational checks;
it is not unrestricted production, enterprise, capacity, or compliance certification.

## Artifact retention

Historical evidence already committed to the repository remains immutable. For future runs, the
[evaluation artifact retention policy](evaluation-artifact-policy.md) defines which integrity and
summary records remain in Git and how large raw attempt data may be retained externally without
weakening reproducibility or privacy controls.
