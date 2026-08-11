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

## Roadmap

1. Business tools — implemented
2. LangGraph agent — implemented
3. Guardrails and confirmation — implemented
4. RAG and knowledge/action routing — implemented
5. Failure handling and human escalation
6. Agent evaluation — implemented
7. Observability
8. Persistent memory
9. Demo UI

The live OpenAI-compatible provider, LangGraph orchestration, deterministic policy engine, confirmation lifecycle, Risk 3 persistence path, deterministic RAG pipeline, knowledge/action routing, and Sprint 5 evaluation harness are implemented, but live LLM, embedding, reranking, and Qdrant services are not required for automated tests. Persistent long-term memory, OpenTelemetry tracing, human operator dashboard/workflow, voice, and multi-agent architecture remain future work.
