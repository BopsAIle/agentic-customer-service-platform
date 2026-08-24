import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentRun } from "../types";
import { buildTraceStages, TraceTimeline } from "./TraceTimeline";

const run: AgentRun = {
  run_id: "run-001",
  request_id: "request-001",
  conversation_id: "conversation-001",
  action_id: "action-001",
  customer_id: 1,
  intent: "refund_order",
  request_type: "action",
  status: "waiting_confirmation",
  started_at: "2026-08-23T00:00:00Z",
  duration_ms: 12,
  trace_id: "trace-001",
  path: ["load_context", "understand_request", "compile_decision", "validate_tool", "evaluate_policy", "create_pending_action"],
  failure_category: null,
  degraded_components: [],
  recovery_action: null,
  memory: { item_count: 0, keys: [], types: [] },
  tools: [],
  policy: [{ action_id: "action-001", tool_name: "refund.create", risk_level: 2, outcome: "require_confirmation", reason_codes: ["risk_2_confirmation"], confirmation_status: "pending" }],
  rag_documents: [],
  retrieval_metadata: { backend: "none", embedding_provider: "none", reranker_enabled: false, retrieval_count: 0, latency_seconds: 0, fallback_status: "none", hybrid: false, fusion_strategy: "none", dense_candidate_count: 0, sparse_candidate_count: 0 },
  decision_reason: "Policy outcome: require_confirmation.",
  evidence: {
    grounding: { status: "grounded", reference_type: "explicit_order", trusted_source: "current_user_message" },
    compiler: { status: "compiled_action", selected_tool: "request_refund", requires_retrieval: false, reason: null },
    target_validation: { status: "validated" },
    confirmation: { status: "pending", required: true, action_id: "action-001", risk_level: 2 },
    write_outcome: { status: "pending_confirmation" },
  },
  trace: [
    { name: "load_context", stage: "user_request", status: "ok", duration_ms: 1.2, timestamp: "2026-08-23T00:00:00Z" },
    { name: "understand_request", stage: "intent_detection", status: "ok", duration_ms: 2.4, timestamp: "2026-08-23T00:00:01Z" },
    { name: "compile_decision", stage: "grounding", status: "ok", duration_ms: 3.1, timestamp: "2026-08-23T00:00:02Z" },
    { name: "validate_tool", stage: "target_validation", status: "ok", duration_ms: 1.8, timestamp: "2026-08-23T00:00:03Z" },
    { name: "evaluate_policy", stage: "policy_evaluation", status: "ok", duration_ms: 1.1, timestamp: "2026-08-23T00:00:04Z" },
    { name: "create_pending_action", stage: "confirmation", status: "ok", duration_ms: 1.4, timestamp: "2026-08-23T00:00:05Z" },
  ],
};

describe("agent trace projection", () => {
  it("derives waiting and blocked states from observed confirmation status", () => {
    const stages = buildTraceStages(run);
    expect(stages.find((stage) => stage.id === "confirmation")?.status).toBe("waiting");
    expect(stages.find((stage) => stage.id === "execution")?.status).toBe("blocked");
  });

  it("keeps absent evidence explicit", () => {
    const html = renderToStaticMarkup(<TraceTimeline events={run.trace} run={run} embedded />);
    expect(html).toContain("No retrieval stage recorded");
    expect(html).toContain("Semantic grounding");
    expect(html).toContain("Context");
    expect(html).toContain("Decision");
    expect(html).toContain("Authority");
    expect(html).toContain("waiting");
  });

  it("renders bounded memory influence metadata when present", () => {
    const memoryRun = {
      ...run,
      memory: {
        item_count: 1,
        keys: ["response_style"],
        types: ["preference"],
        retrieved: true,
        retrieved_count: 1,
        items_used: 1,
        purpose: "context_enrichment" as const,
        decision_influence: "context_only" as const,
        authority_influence: "none" as const,
      },
      trace: [
        ...run.trace,
        {
          name: "retrieve_memory",
          stage: "memory_context" as const,
          status: "ok",
          duration_ms: 0.8,
          timestamp: "2026-08-23T00:00:00Z",
          metadata: { items_used: 1, role: "context_enrichment" },
        },
      ],
    };
    const html = renderToStaticMarkup(<TraceTimeline events={memoryRun.trace} run={memoryRun} embedded />);
    expect(html).toContain("Memory context");
    expect(html).toContain("Customer state");
    expect(html).toContain("Knowledge retrieval");
    expect(html).toContain("items used: 1");
    expect(html).toContain("role: context enrichment");
  });

  it("presents human-readable event names before technical keys", () => {
    const html = renderToStaticMarkup(<TraceTimeline events={run.trace} run={run} embedded />);
    expect(html).toContain("Intent detection");
    expect(html).toContain("understand_request");
    expect(html.indexOf("Intent detection")).toBeLessThan(html.indexOf("understand_request"));
  });

  it("renders bounded workflow transition metadata", () => {
    const transitionRun = {
      ...run,
      trace: [
        ...run.trace,
        {
          name: "handle_workflow_interruption",
          event_key: "workflow.superseded",
          stage: "routing" as const,
          status: "ok",
          duration_ms: 0.4,
          timestamp: "2026-08-23T00:00:02Z",
          metadata: {
            workflow_state: "superseded",
            workflow_transition: "waiting_confirmation_to_superseded",
            previous_workflow_intent: "refund_request",
            interruption_intent: "order_cancel",
            interruption_type: "explicit_replacement",
          },
        },
      ],
    };

    const html = renderToStaticMarkup(
      <TraceTimeline events={transitionRun.trace} run={transitionRun} embedded />,
    );
    expect(html).toContain("Workflow transition");
    expect(html).toContain("Workflow Superseded");
    expect(html).toContain("explicit replacement");
  });

  it("does not present a business intent stage for a security boundary", () => {
    const securityRun = {
      ...run,
      security_signal: "instruction_override_attempt",
    };
    const html = renderToStaticMarkup(<TraceTimeline events={securityRun.trace} run={securityRun} embedded />);
    expect(html).not.toContain("Intent detection");
  });
});
