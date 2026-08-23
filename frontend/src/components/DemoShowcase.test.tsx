import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DemoShowcase } from "./DemoShowcase";
import type { DemoScenario } from "../types";

const scenario: DemoScenario = {
  scenario_id: "refund-memory-rag",
  title: "Refund request with memory + RAG",
  purpose: "A bounded refund scenario.",
  expected: "Confirmation required.",
  proposal_confidence: 0.94,
  messages: [
    { role: "customer", content: "My headphones stopped working.", timestamp: null, state: null, evidence_tags: ["Memory"] },
    { role: "agent", content: "I found the applicable policy.", timestamp: null, state: "waiting_confirmation", evidence_tags: ["RAG", "Policy"] },
  ],
  memory_evidence: [{ category: "customer_preference", summary: "Bounded preference metadata", source: "customer_memory", authority: "context_only", purpose: "context_enrichment" }],
  run: {
    run_id: "demo-run",
    request_id: "demo-request",
    conversation_id: "demo-conversation",
    action_id: "demo-action",
    customer_id: 1,
    intent: "refund_request",
    request_type: "action",
    status: "waiting_confirmation",
    started_at: "2026-08-23T09:00:00Z",
    duration_ms: 0,
    trace_id: null,
    path: [],
    failure_category: null,
    degraded_components: [],
    recovery_action: null,
    memory: { item_count: 1, keys: ["refund_preference"], types: ["customer_preference"], retrieved: true, retrieved_count: 1, items_used: 1, context_usage: "context_enrichment", purpose: "context_enrichment", decision_influence: "context_only", authority_influence: "none" },
    tools: [],
    policy: [{ action_id: "demo-action", tool_name: "refund.create", risk_level: 2, outcome: "require_confirmation", reason_codes: ["confirmation_required"] }],
    rag_documents: [{ citation_id: "refund-policy-v3", title: "Refund Policy v3", section: "Damaged products", source: "refund_policy_v3.md", score: 0.94, chunk_id: "refund-30-day", document_version: "v3", grounding_status: "validated", citation_preview: "Defective products are eligible after verification." }],
    retrieval_metadata: { backend: "recorded_demo", embedding_provider: "not_applicable", reranker_enabled: false, retrieval_count: 1, latency_seconds: 0, fallback_status: "not_applicable", hybrid: false, fusion_strategy: "not_applicable", dense_candidate_count: 0, sparse_candidate_count: 0 },
    trace: [],
    decision_reason: "Customer confirmation required before mutation.",
    evidence: { grounding: { status: "validated", reference_type: "policy", trusted_source: "refund_policy_v3.md" }, compiler: { status: "passed", selected_tool: "refund.create", requires_retrieval: true, reason: "Target and required fields validated." }, target_validation: { status: "validated" }, confirmation: { status: "pending", required: true, action_id: "demo-action", risk_level: 2 }, write_outcome: { status: "pending_confirmation" } },
    execution_mode: "recorded_replay",
    provider: "recorded_demo",
    model: null,
    fallback_message: null,
    proposal: { intent: "refund_request", suggested_action: "refund.create", extracted_fields: {}, evidence_references: ["refund-policy-v3"], validation: "passed" },
    provider_metadata: null,
  },
};

describe("demo showcase presentation", () => {
  it("renders product evidence without developer configuration or execution controls", () => {
    const html = renderToStaticMarkup(<DemoShowcase scenarios={[scenario]} />);
    expect(html).toContain("Production Agent Control Plane");
    expect(html).toContain("Customer request");
    expect(html).toContain("Decision compiler");
    expect(html).toContain("Controlled runtime execution");
    expect(html).toContain("Customer request to controlled response");
    expect(html).toContain("Customer request to controlled response");
    expect(html).toContain("Agent response");
    expect(html).toContain("Decision boundary");
    expect(html).toContain("Awaiting confirmation");
    expect(html).toContain("Recorded conversation turns");
    expect(html).toContain("Memory context");
    expect(html).toContain("RAG grounding");
    expect(html).toContain("LLM proposal");
    expect(html).toContain("Deterministic decision validation");
    expect(html).toContain("Investigation summary");
    expect(html).toContain("View investigation report");
    expect(html).toContain("Evidence role");
    expect(html).toContain("Memory informs context but cannot grant authority.");
    expect(html).toContain("Not execution authority");
    expect(html).not.toContain("API configuration");
    expect(html).not.toContain("Run agent");
  });
});
