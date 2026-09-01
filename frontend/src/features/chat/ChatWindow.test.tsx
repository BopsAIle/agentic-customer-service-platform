import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentResponse } from "../../types";
import { ChatWindow, agentState } from "./ChatWindow";
import { CHAT_CONVERSATIONS_KEY } from "./conversationStore";

class MemoryStorage {
  private data = new Map<string, string>();
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  getItem(key: string) { return this.data.has(key) ? this.data.get(key)! : null; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  removeItem(key: string) { this.data.delete(key); }
  setItem(key: string, value: string) { this.data.set(key, String(value)); }
}

function installStorage() {
  Object.defineProperty(globalThis, "localStorage", { value: new MemoryStorage(), configurable: true });
  Object.defineProperty(globalThis, "sessionStorage", { value: new MemoryStorage(), configurable: true });
}

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
  beforeEach(() => {
    installStorage();
  });

  afterEach(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      /* node without storage */
    }
  });

  it("renders customer conversation, activity timeline, and runtime details", () => {
    const html = renderToStaticMarkup(<ChatWindow />);
    expect(html).toContain("Customer conversation + agent observability");
    expect(html).toContain("Agent timeline");
    expect(html).toContain("Runtime details");
    expect(html).toContain("Send");
    expect(html).toContain("No prompts or hidden reasoning are shown");
    expect(html).toContain("New chat");
    expect(html).toContain("conversation-history");
  });

  it("lists persisted conversations beside the transcript", () => {
    localStorage.setItem(CHAT_CONVERSATIONS_KEY, JSON.stringify([{
      conversationId: "chat-abc123",
      customerId: 1,
      updatedAt: "2026-09-01T12:00:00.000Z",
      title: "I received a damaged product",
      messages: [{ id: "1", role: "customer", content: "I received a damaged product", timestamp: "2026-09-01T12:00:00.000Z" }],
      lastRunId: null,
    }]));
    const html = renderToStaticMarkup(<ChatWindow />);
    expect(html).toContain("I received a damaged product");
    expect(html).toContain("Customer #1");
    expect(html).toContain("chat-abc123");
  });

  it("maps bounded agent response states without exposing reasoning", () => {
    expect(agentState(response())).toBe("awaiting confirmation");
    expect(agentState(response({ pending_action: null, tool_call: { name: "refund", status: "executed", result: null } }))).toBe("completed");
    expect(agentState(response({ pending_action: { action_id: "act_test", status: "rejected" }, error_category: null }))).toBe("blocked");
    expect(agentState(response({ pending_action: null, error_category: "policy_denied" as AgentResponse["error_category"] }))).toBe("blocked");
  });
});
