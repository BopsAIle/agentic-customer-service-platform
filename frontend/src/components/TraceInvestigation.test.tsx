import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentRun } from "../types";
import { DecisionExplanationCard, DecisionLifecycleSummary, EvidenceRelationshipGraph, InvestigationReportModal, OperationalTraceTimeline, TraceInvestigationHeader } from "./TraceInvestigation";

const run: AgentRun = {
  run_id: "agent_run_8f31a2",
  request_id: "request-001",
  conversation_id: "conversation-001",
  action_id: "action-001",
  customer_id: 1,
  intent: "refund_request",
  request_type: "write_action",
  status: "waiting_confirmation",
  started_at: "2026-08-23T09:00:00Z",
  duration_ms: 842,
  trace_id: "trace-8f31a2",
  path: [],
  failure_category: null,
  recovery_action: null,
  degraded_components: [],
  memory: { item_count: 1, keys: ["refund_preference"], types: ["customer_preference"], retrieved: true, retrieved_count: 1, items_used: 1, context_usage: "context_enrichment", purpose: "context_enrichment", decision_influence: "context_only", authority_influence: "none" },
  tools: [],
  policy: [{ action_id: "action-001", tool_name: "refund.create", risk_level: 2, outcome: "require_confirmation", reason_codes: ["confirmation_required"] }],
  rag_documents: [{ citation_id: "refund-policy", title: "Refund Policy v3", section: "Defective products", source: "refund_policy_v3.md", score: 0.91, grounding_status: "validated" }],
  retrieval_metadata: { backend: "recorded_demo", embedding_provider: "not_applicable", reranker_enabled: false, retrieval_count: 1, latency_seconds: 0, fallback_status: "not_applicable", hybrid: false, fusion_strategy: "not_applicable", dense_candidate_count: 0, sparse_candidate_count: 0 },
  trace: [],
  decision_reason: "Customer confirmation required before mutation.",
  evidence: { grounding: { status: "validated", reference_type: "rag", trusted_source: "refund_policy_v3.md" }, compiler: { status: "passed", selected_tool: "refund.create", requires_retrieval: true, reason: "Target and required fields validated." }, target_validation: { status: "validated" }, confirmation: { status: "pending", required: true, action_id: "action-001", risk_level: 2 }, write_outcome: { status: "pending_confirmation" } },
  proposal: { intent: "refund_request", suggested_action: "refund.create", extracted_fields: {}, evidence_references: ["refund-policy"], validation: "passed" },
};

describe("trace investigation surface", () => {
  it("renders header, decision explanation, relationship graph, and operational stages", () => {
    const html = renderToStaticMarkup(<><TraceInvestigationHeader run={run} /><DecisionLifecycleSummary run={run} /><OperationalTraceTimeline run={run} /><DecisionExplanationCard run={run} /><EvidenceRelationshipGraph run={run} /></>);
    expect(html).toContain("Trace investigation");
    expect(html).toContain("Request received");
    expect(html).toContain("Request accepted");
    expect(html).toContain("Actor / layer");
    expect(html).toContain("Knowledge source resolved");
    expect(html).toContain("Action proposal recorded");
    expect(html).toContain("Policy decision evaluated");
    expect(html).toContain("Outcome");
    expect(html).toContain("Execution not attempted");
    expect(html).toContain("Memory snapshot loaded");
    expect(html).toContain("Knowledge source resolved");
    expect(html).toContain("Decision compiler");
    expect(html).toContain("Why this decision?");
    expect(html).toContain("Satisfied checks");
    expect(html).toContain("Decision lifecycle");
    expect(html).toContain("Execution was not granted because the confirmation requirement was not satisfied.");
    expect(html).toContain("Evidence relationships");
    expect(html).toContain("Authority boundary");
    expect(html).toContain("Memory evidence");
    expect(html).toContain("Decision compiler");
    expect(html).toContain("Evidence snapshot metadata");
  });

  it("renders a bounded report modal without hidden reasoning", () => {
    const html = renderToStaticMarkup(<InvestigationReportModal run={run} onClose={() => undefined} onExport={() => undefined} />);
    expect(html).toContain("Agent Investigation Report");
    expect(html).toContain("Evidence collected");
    expect(html).toContain("Evidence available");
    expect(html).toContain("Deterministic decision");
    expect(html).toContain("Authority");
    expect(html).toContain("Outcome");
    expect(html).toContain("No hidden reasoning");
    expect(html).not.toContain("chain_of_thought");
    expect(html).not.toContain("raw_provider_response");
  });
});
