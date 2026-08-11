# Agentic Customer Service Platform

This portfolio project will grow into an enterprise-style AI customer service platform with stateful workflows, business actions, retrieval, authorization, evaluation, and observability.

## Sprint 0 and Sprint 1

Sprint 0 established the production-oriented FastAPI foundation. Sprint 1 added typed business tools and domain actions. Sprint 2 added a stateful LangGraph orchestration core. Sprint 3 added deterministic policy, confirmation, revalidation, and human escalation. Sprint 4 adds a knowledge layer and explicit knowledge/action routing. The tool layer receives database sessions explicitly; agents never query the database or call HTTP handlers directly.

## Stack and architecture

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL, Alembic, LangGraph, Qdrant, an OpenAI-compatible LangChain provider, pytest, Ruff, mypy, Docker, and Docker Compose. HTTP routes and the agent call the same explicit tools. Tools validate typed inputs, enforce ownership and state rules, and raise domain errors. Services own basic persistence queries; models and typed response schemas remain separate. Tables are created through Alembic, never on application startup.

## Setup

```bash
cp .env.example .env
make up
make migrate
make seed
```

For local development with `uv`, use `uv sync` and `make dev`. The API is available at `http://localhost:8000`.

## Commands

`make up`, `make down`, `make test`, `make lint`, `make typecheck`, `make migrate`, `make seed`, `make rag-ingest`, and `make rag-reset` provide the main development workflow. `make dev` runs Uvicorn with reload. RAG ingestion reads the version-controlled Markdown knowledge base and upserts deterministic UUID-keyed points into Qdrant.

## API

- `GET /health`
- `GET /customers/{customer_id}`
- `GET /customers/{customer_id}/orders`
- `GET /customers/{customer_id}/tickets`
- `GET /orders/{order_id}`
- `GET /tickets/{ticket_id}`
- `POST /tickets`
- `POST /orders/{order_id}/cancel`
- `POST /orders/{order_id}/refunds`
- `POST /escalations`
- `POST /agent/chat`
- `GET /customers/{customer_id}/memories`
- `DELETE /customers/{customer_id}/memories/{memory_id}`

## Sprint 2–4 agent core

The agent uses an explicit LangGraph flow:

```text
load_context → check_pending_action
  ├─ confirmation → policy_revalidation → execute_confirmed_action → respond
  └─ new request → understand_request → select_tool → validate_tool
       → evaluate_policy → allow/confirm/human → execute/respond
```

The typed state contains the conversation ID, customer ID, message history, intent, request type, selected tool, validated arguments, tool result, pending action, retry count, error category, final response, and agent run ID. The graph uses `MemorySaver` keyed by `conversation_id` for short-term state during the process lifetime.

Structured decisions use the explicit intent taxonomy: `customer_lookup`, `order_lookup`, `order_list`, `ticket_lookup`, `ticket_list`, `ticket_create`, `order_cancel`, `refund_request`, `human_escalation`, `capability_question`, `refund_policy`, `cancellation_policy`, `shipping_policy`, `support_faq`, `refund_eligibility`, `cancellation_explanation`, and `unknown`. Request types additionally include `knowledge_only`, `action_only`, and `knowledge_and_action`.

The model returns validated Pydantic decisions rather than prose tool calls. The agent checks the Sprint 1 registry, validates arguments against each existing tool input schema, enforces the authenticated conversation customer for customer-scoped arguments, and maps expected domain failures to safe responses.

Risk 0 and Risk 1 tools execute automatically after deterministic policy evaluation. Risk 2 tools create a typed `PendingAction` with a stable `action_id`, validated arguments, customer/conversation ownership, creation time, and `pending` status. Risk 3 tools use a dedicated policy-approved escalation path and persist the existing escalation record through the Sprint 1 business tool.

## Sprint 3 policy and confirmation

The policy engine is independent of the LLM provider and HTTP layer. It reads the registered tool risk metadata and returns `allow`, `require_confirmation`, `require_human`, or `deny`, with reason codes and required conditions. The LLM proposes an action; it never authorizes one.

Confirmation parsing is deterministic and intentionally bounded (`yes`, `confirm`, `proceed`, `do it`, and clear rejections). A confirmation executes only the exact stored `PendingAction`; the model is not called to regenerate the tool or arguments. Ambiguous text, action substitution, another customer, another conversation, expired actions, and terminal actions cannot execute.

Before a confirmed Risk 2 action executes, the current ownership and business-state validators run again. For example, a cancellation pending while an order is processing is rejected if the order becomes shipped before confirmation. Pending actions expire after `CONFIRMATION_TTL_SECONDS` (default 300 seconds), and their lifecycle is explicit: `pending`, `confirmed`, `rejected`, `expired`, `executed`, or `failed`.

Policy decisions are recorded in an in-memory structured audit log containing the agent run, conversation, action, tool, risk, outcome, reason codes, and timestamp. It is an instrumentation seam only; it is not persistent storage.

The default provider targets an OpenAI-compatible endpoint using `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_TEMPERATURE`, and `LLM_TIMEOUT_SECONDS`. Tests use a deterministic fake structured-decision provider and never require an LLM, API key, or network access.

## Sprint 4 knowledge layer

Knowledge documents live in `app/knowledge/` and cover fictional refund, cancellation, shipping, subscription, and support FAQ policies. Ingestion parses Markdown, splits it into stable section chunks, preserves document metadata, and upserts idempotently into the configured Qdrant collection. The deployment adapter persists dense embeddings; the local deterministic retrieval service combines dense cosine search with BM25-style sparse search, weighted fusion, and a swappable reranker. A lazy cross-encoder adapter is available for deployments that install a sentence-transformers model; tests use deterministic providers.

The graph routes `knowledge_only` requests through retrieval and grounded response generation, keeps `action_only` requests on the existing tool/policy path, and combines a read tool with retrieval for `knowledge_and_action` requests. Context construction deduplicates and limits chunks. Responses expose citations generated only from retrieved `document_id#section` metadata. If retrieval has insufficient evidence, the response uses a bounded fallback.

Authority is deliberately separated: customer/order/ticket state comes only from business tools, policy facts come from retrieved evidence, and authorization remains in the Sprint 3 policy engine. Retrieved documents are untrusted data; embedded instructions cannot select tools, authorize actions, or override business state. For example, a policy explanation can cite cancellation-before-shipment guidance while the actual order status from `get_order` remains decisive.

The current application runtime uses the deterministic local retriever so tests and development do not require a running Qdrant or model service. `make rag-ingest` exercises the Qdrant persistence path. Short-term LangGraph state remains in-process via `MemorySaver` and is not durable across restarts.

## Sprint 1 business tools

Read-only tools: `get_customer`, `get_customer_orders`, `get_order`, `get_customer_tickets`, and `get_ticket`.

Write tools: `create_support_ticket`, `cancel_order`, `request_refund`, and `escalate_to_human`.

The deterministic tool registry exposes each tool's name, description, read/write operation type, and risk level. Risk 0 is read-only, Risk 1 is a low-risk support action, Risk 2 requires confirmation, and Risk 3 requires the dedicated human escalation path.

Business rules include cancellation only for pending/processing orders, idempotent repeated cancellation, refunds only for delivered orders with no active duplicate request, and strict customer ownership checks for all referenced resources. Escalations are persisted with queued status and structured priority/reason/summary fields.

## Sprint 5 evaluation

Normal unit tests verify implementation correctness; agent evaluation verifies observable behavior across complete scenarios. The offline suite in `evaluation/` uses versioned JSONL scenarios, a deterministic fake decision provider, fresh SQLite state per scenario, and isolated multi-turn checkpoints. It stores no chain-of-thought.

Run it with `make eval`, or run the safety slice with `make eval-safety`. Results are computed into `evaluation/results/latest.json` and `evaluation/results/latest.md`. The report covers intent and request-type accuracy, tool selection and important arguments, task completion, confirmation compliance, unauthorized actions, escalation, citation integrity, and deterministic failure recovery. The current dataset contains 72 scenarios: 10 knowledge, 10 read action, 10 Risk 2 write, 10 confirmation, 10 failure/recovery, 10 adversarial/safety, 10 human-escalation, plus explicit knowledge-and-action and multi-turn cases. Multi-turn coverage is included across these groups.

Evaluation faults are scoped to one scenario: malformed provider output, retriever empty/error, simulated tool timeout/error, missing resources, invalid arguments, ownership failures, and invalid business state. A scenario receives a new schema and seed, so write actions cannot affect later cases. Use `python -m evaluation.runner --compare evaluation/results/baseline.json` for a metric delta report. `make eval-baseline` saves a baseline only when one does not already exist; it never silently overwrites it.

The default CI gate is offline and deterministic. It exits non-zero for any unauthorized action, less than 100% confirmation compliance, failed critical safety scenarios, or quality metrics below their explicit 90% thresholds. A live-model mode is intentionally optional and is not needed for CI.

Known limitations: the fake provider does not model real LLM nondeterminism, RAG grounding checks are rule-based rather than a perfect semantic judge, the synthetic dataset is portfolio-scale rather than production traffic, and fake-provider latency is not representative of a live model.

## Observability

Sprint 6 adds provider-agnostic OpenTelemetry tracing and metrics. An enabled agent request creates an `agent.run` root span with bounded identifiers and safe outcome attributes. Meaningful graph nodes appear below it, with nested spans for `llm.structured_decision`, `policy.evaluate`, `policy.revalidate`, `confirmation.evaluate`, `tool.execute`, escalation, and the RAG stages (`rag.retrieve`, embedding, dense search, sparse search, fusion, rerank, and context construction).

The application records `agent_runs_total`, agent duration, tool calls/duration/errors, RAG requests/duration, policy decisions, confirmation results, escalations, and agent errors. Labels are limited to bounded categories such as intent, request type, tool, risk, status, and policy outcome; customer IDs, conversation IDs, order IDs, and free-form errors are never metric labels.

Tracing is disabled by default for local tests. Compose enables OTLP export to Jaeger:

```bash
make observability-up
# Jaeger UI: http://localhost:16686
make observability-down
```

The local settings are `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_SERVICE_NAME`. OTLP uses Jaeger’s gRPC port `4317`. The trace data intentionally excludes raw user messages, prompts, model responses, retrieved document content, customer names/emails, free-form tool arguments, and hidden model reasoning. Trace attributes use only bounded IDs/statuses/categories needed to correlate an agent run safely.

## Failure Hardening & Degraded Modes

Sprint 8 adds a small centralized resilience layer. Failures are classified before a bounded retry or fallback is chosen; deterministic business-rule errors are never retried.

| Failure | Behavior |
| --- | --- |
| LLM timeout/unavailable/malformed output | bounded structured-decision retry, then clarify safely |
| Read tool or database transient failure | bounded retry, then safe failure |
| Write failure with unknown outcome | no blind replay; report ambiguity |
| Reranker unavailable | retain dense+sparse fused results |
| RAG unavailable | no policy hallucination; preserve business result when available |
| Empty retrieval | grounded insufficient-evidence response |
| Memory unavailable | continue without memory; explicit writes report failure |
| Policy failure | fail closed; no pending or executed write |
| Retry exhaustion | bounded safe failure or degraded response |

Retries use `RESILIENCE_MAX_RETRIES`, `RESILIENCE_INITIAL_BACKOFF_MS`, and `RESILIENCE_MAX_BACKOFF_MS`. Backoff is injectable in tests and does not replay writes. Existing pending `action_id` confirmation state remains deterministic, so `yes`/`no` confirmation turns do not require an LLM. Unknown write outcomes are marked non-replayable and are never automatically repeated.

Resilience telemetry adds `resilience.retry`, `resilience.recovery`, and degraded-mode events plus `dependency_failures_total`, `retry_attempts_total`, `retry_exhausted_total`, and `degraded_requests_total`. Labels contain only bounded dependency, failure, and component values. The deterministic evaluation suite contains 110 scenarios, including 21 new failure/degraded-mode cases; run `make eval-resilience` for the focused 28-case slice.

## Persistent Agentic Memory

Sprint 7 adds selective persistent memory backed by PostgreSQL. It is separate from short-term LangGraph conversation state, authoritative customer/order/ticket business state, RAG knowledge, and action authorization. Memory is contextual evidence for personalization; it cannot select tools, confirm Risk 2 actions, override business state, or bypass the policy engine.

The bounded taxonomy is `preference`, `support_context`, `explicit_instruction`, `unresolved_issue`, and `interaction_summary`. Raw transcripts, tool arguments, confirmation state, payment data, credentials, tokens, hidden reasoning, retrieved chunks, and full escalation summaries are never stored. Candidates are structured and passed through a deterministic policy: safe durable preferences may be retained, broader context requires an explicit remember request, and sensitive or instruction-injection content is rejected.

Users can say `Remember that I prefer email updates.` or `Forget my email preference.`. Forget requests need a resolvable target; vague requests clarify instead of deleting all memories. Repeated values are deduplicated, conflicting values with the same normalized key supersede the old active value, and temporary support context expires lazily. Retrieval is customer-scoped, lexical/recency-ranked, and bounded by `MEMORY_MAX_CONTEXT_ITEMS`. The memory context is explicitly marked untrusted before it reaches the provider.

Authority ordering remains strict: policy engine > business tool state > current user request > RAG knowledge > persistent memory. For example, a stored preference cannot satisfy a pending confirmation, and a stored belief that an order is refundable cannot replace a fresh business-state and policy check. Memory spans (`memory.retrieve`, `memory.evaluate_candidate`, `memory.forget`) record only type, outcome, count, and status; memory content is not telemetry.

Memory is enabled by `MEMORY_ENABLED=true` and configured with `MEMORY_MAX_CONTEXT_ITEMS`, `MEMORY_DEFAULT_TTL_DAYS`, and `MEMORY_SUPPORT_CONTEXT_TTL_DAYS`. Set `MEMORY_ENABLED=false` to preserve Sprint 0–6 behavior without reads or writes. The default evaluation suite includes persistent-memory scenarios for consent, isolation, expiry, conflict resolution, injection boundaries, business authority, and confirmation safety.

## Roadmap

1. Business tools — implemented
2. LangGraph agent — implemented
3. Guardrails and confirmation — implemented
4. RAG and knowledge/action routing — implemented
5. Failure handling and human escalation
6. Agent evaluation — implemented
7. Observability — implemented
8. Persistent memory — implemented
9. Failure hardening — implemented
10. Demo UI

The live OpenAI-compatible provider, LangGraph orchestration, deterministic policy engine, confirmation lifecycle, Risk 3 persistence path, deterministic RAG pipeline, knowledge/action routing, evaluation harness, OpenTelemetry tracing, selective persistent memory, and failure hardening are implemented, but live LLM, embedding, reranking, and Qdrant services are not required for automated tests. Timeout enforcement for synchronous local adapters remains deployment-specific; unknown write outcomes require an adapter to report that ambiguity explicitly. Human operator dashboard/workflow, voice, and multi-agent architecture remain future work.
