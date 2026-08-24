import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatWindow, agentState } from "./ChatWindow";
import type { AgentResponse } from "../../types";

const response = (overrides: Partial<AgentResponse> = {}): AgentResponse => ({
  conversation_id: "chat-test",
  agent_run_id: "run-test",
  message: "Confirmation is required before processing.",
  intent: "refund_order" as AgentResponse["intent"],
  request_type: "mutation" as AgentResponse["request_type"],
  tool_call: null,
  pending_action: { action_id: "act_test", status: "pending" },
  decision_reason: "Confirmation required.",
  error_category: null,
  citations: [],
  failure_category: null,
  degraded_components: [],
  recovery_action: null,
  write_outcome_unknown: false,
  execution_mode: "recorded_replay",
  provider: "recorded_evidence",
  model: null,
  fallback_message: null,
  proposal: null,
  provider_metadata: null,
  ...overrides,
});

describe("unified chat experience", () => {
  it("renders customer conversation, activity timeline, and runtime details", () => {
    const html = renderToStaticMarkup(<ChatWindow />);
    expect(html).toContain("Customer conversation + agent observability");
    expect(html).toContain("Agent timeline");
    expect(html).toContain("Runtime details");
    expect(html).toContain("Send");
    expect(html).toContain("No prompts or hidden reasoning are shown");
  });

  it("maps bounded agent response states without exposing reasoning", () => {
    expect(agentState(response())).toBe("waiting confirmation");
    expect(agentState(response({ pending_action: null, tool_call: { name: "refund", status: "executed", result: null } }))).toBe("completed");
    expect(agentState(response({ pending_action: null, error_category: "policy_denied" as AgentResponse["error_category"] }))).toBe("contained");
  });
});
