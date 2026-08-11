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

The default provider is offline and deterministic. An optional live-model adapter can be added later, but live models are not required for CI. The current rule-based citation and grounding checks are intentionally conservative and do not replace a semantic judge.
