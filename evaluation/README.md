# Evaluation harness

This package evaluates observable agent behavior without storing chain-of-thought. Scenarios are versioned Pydantic models stored as JSONL, and their deterministic structured decisions are fed through the real LangGraph runtime.

Each scenario receives a fresh SQLite schema and seed. A multi-turn scenario keeps a private in-memory checkpoint for its own conversation only. Faults are injected through temporary provider/retriever wrappers or a scoped tool-definition replacement that is restored in `finally`.

Commands:

```bash
make eval
make eval-safety
make eval-resilience
python -m evaluation.runner --compare evaluation/results/baseline.json
make eval-baseline
```

The runner writes JSON and Markdown reports, compares metric deltas, and exits non-zero for unauthorized actions, confirmation-compliance failures, failed critical safety scenarios, or quality metrics below 90%. Baselines are opt-in and never overwritten implicitly.

The default suite covers knowledge, read actions, Risk 2 writes, confirmations, knowledge-and-action routing, human escalation, ownership, prompt injection, ambiguity, multi-turn state, missing resources, invalid arguments, invalid business states, simulated tool faults, malformed provider output, and retrieval faults.

The memory slice adds scenarios for explicit remember/forget, consent-gated candidates, customer isolation, lazy expiry, deduplication, conflict superseding, malicious stored content, business-state authority, and the invariant that persistent memory cannot confirm a Risk 2 action. Memory scenarios seed only structured records; they never store transcripts.

The resilience slice uses scoped fault injection for LLM, retrieval, tools, database boundaries, policy, and memory. It covers bounded retry and exhaustion, confirmation without an LLM call, RAG and reranker degradation, fail-closed policy errors, unknown write outcomes, and no duplicate writes. Run it with `make eval-resilience`.

The citation-constrained answer audit contains 20 deterministic grounding cases covering citation coverage, irrelevant or empty evidence, conflicting sources, and unsupported-answer rejection. It performs no provider calls and can be run with `make eval-rag-grounding`.

The default evaluation provider and knowledge fixtures are offline and deterministic; live models
and Qdrant are not required for CI. Runtime RAG hooks are separate and measure retrieval success,
citation availability, reranker use, fallback behavior, and latency. The current rule-based
citation and grounding checks are intentionally conservative and do not claim live-model accuracy
or replace a semantic judge.

## Live scoring versions

The historical hosted live benchmark uses the `direct_tool_v1` decision contract. Historical reports
remain reproducible with `live_scoring_v2`. The versioned `live_scoring_v3` scorer re-scores the
same frozen raw attempts without invoking a model or changing cases, prompts, or model outputs.
It separates action-tool selection, correct no-tool abstention, and overall routing, and adds
case-level, paired EN/TR, consistency, failure-cluster, and tool-confusion reporting. Previous
live results used `live_scoring_v2`, whose legacy tool-selection metric did not represent correct
no-tool abstention as routing success. Re-scoring changes only the interpretation of the stored
attempts.

Use the offline rescore path with a new destination under `artifacts/live-eval/rescored/`:

```bash
python -m evaluation.live rescore \
  --input artifacts/live-eval/qwen2_5_7b_instruct_20260812T213229Z.json \
  --scoring-version live_scoring_v3
```

## Live benchmark provenance

New live reports include `benchmark_provenance_v1` as a machine-readable `provenance` object.
It records the model/provider, runtime and transport, the configured structured-output mode,
reasoning effort, temperature, timeout and retry boundary, privacy-safe hardware metadata,
the `direct_tool_v1` decision-contract version and schema hash, benchmark identity, source
revision, and nullable usage/cost fields. Provider, runtime, and transport are separate: an
OpenAI-compatible transport may serve a local Ollama runtime or a hosted service.

Model name, exact identifier, digest, quantization, and parameter count are recorded only when
the runtime can provide them; unavailable values remain `null`. Local cost is represented as
`cost_status: not_applicable`, while hosted cost is `available` only when supplied by existing
runtime metadata and is never inferred from hard-coded pricing. The provenance collector uses
an allowlist and does not serialize environment dumps, credentials, prompts, hidden reasoning,
hostnames, serials, UUIDs, MAC addresses, or IP addresses.

The decision-contract version (`direct_tool_v1`) identifies the executable structured decision
contract. Its schema hash is a canonical SHA-256 of the sorted, compact JSON schema for
`StructuredDecision`; it is distinct from the benchmark scoring version. Offline v3 rescoring
preserves source runtime provenance when present and adds separate derived-scoring metadata.
Historical artifacts without provenance are not rewritten; fields that cannot be recovered
reliably remain unavailable.

## Decision contract architecture

The runtime supports three explicit contracts. The default runnable path uses
`semantic_decision_v3`; `direct_tool_v1` remains an explicit compatibility and historical-evidence
mode:

| Contract | Model responsibility | Application responsibility |
| --- | --- | --- |
| `direct_tool_v1` | Select an executable tool and propose its arguments | Validate, authorize, confirm, execute, and audit |
| `semantic_decision_v2` | Propose intent, user entities/references, and clarification semantics | Compile canonical actions, resolve business targets, validate, authorize, confirm, execute, and audit |
| `semantic_decision_v3` | Propose the same semantics through transport-visible discriminated target branches | Use the same grounding, admissibility, compiler, resolver, validation, policy, and execution path |

In `semantic_decision_v2`, the model cannot choose an arbitrary tool or provide trusted customer
scope. The compiler constructs allow-listed arguments from semantic fields and
`ExecutionContext`; read-only business resolution handles symbolic references such as
`latest_order`. Business existence, ownership, current state, eligibility, confirmation, action
identity, idempotency, and replay remain downstream control-plane responsibilities.

`semantic_decision_v2` and `live_eval_v1` remain frozen historical evidence. New compatibility
work uses `semantic_decision_v3` with `live_eval_v1_1`. The v1.1 case set changes only the paired
fake-order identifiers from a synthetic alphanumeric token to a positive integer outside the
deterministic fixture domain; case identities, pairing, intents, risks, and safety labels remain
unchanged.
