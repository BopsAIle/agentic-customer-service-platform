# Estimated Cost Model

This document is a provider-neutral planning model for the reference
implementation. It is not measured billing, a quotation, or a production cost
commitment. The model does not call OpenAI or another external provider.

## Workload assumptions

The example profile is intentionally explicit so it can be replaced with
measured provider pricing later:

| Input | Planning value |
|---|---:|
| Input tokens per conversation | 1,200 |
| Output tokens per conversation | 400 |
| Embedding chunks per request | 8 |
| Reranking candidates | 12 |
| Requests in a planning unit | 1,000 |

Generation, embedding, and reranking prices are variables. Substitute the
provider's current published rates before using the model for a budget.

## Formula

For a request:

```text
estimated_ai_cost =
  (input_tokens / 1,000,000 * input_price_per_million)
  + (output_tokens / 1,000,000 * output_price_per_million)
  + (embedding_chunks * embedding_price_per_chunk)
  + (rerank_candidates * rerank_price_per_candidate)
```

The same formula scales linearly to 1,000, 100,000, or 1,000,000 requests.
The repository keeps these as variables rather than embedding a provider price
that may become stale.

## Infrastructure cost categories

Infrastructure planning is separate from AI cost:

- API replicas: compute, ingress, and outbound traffic.
- PostgreSQL: primary compute, storage, backups, pooling, and replicas.
- Qdrant: vector compute, storage, replicas, and index rebuild capacity.
- Evidence storage: immutable payload storage, requests, retention, and egress.
- Observability: metrics, traces, logs, and retention.

The deterministic benchmark reports throughput and latency summaries but does
not convert them into a capacity or cloud-price guarantee. Production planning
must combine measured workload data with the selected deployment provider's
rates and resilience requirements.

## Privacy and authority boundary

Cost summaries contain only bounded counts, durations, and statuses. They do
not contain prompts, customer data, tool arguments, tokens, provider responses,
or secrets. Measurement code is not part of the decision or execution path.
