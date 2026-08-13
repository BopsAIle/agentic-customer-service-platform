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

The default evaluation provider and knowledge fixtures are offline and deterministic; live models
and Qdrant are not required for CI. Runtime RAG hooks are separate and measure retrieval success,
citation availability, reranker use, fallback behavior, and latency. The current rule-based
citation and grounding checks are intentionally conservative and do not claim live-model accuracy
or replace a semantic judge.

## Live scoring versions

The hosted live benchmark currently uses the `direct_tool_v1` decision contract. Historical reports
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
