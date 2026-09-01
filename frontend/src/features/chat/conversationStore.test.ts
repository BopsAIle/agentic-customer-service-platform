import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentResponse, ConversationTurn } from "../../types";
import type { ChatMessage } from "./MessageBubble";
import {
  CHAT_CONVERSATIONS_KEY,
  LEGACY_CHAT_SESSION_KEY,
  MAX_CONVERSATIONS,
  TITLE_MAX_CHARS,
  WORKSPACE_CONVERSATIONS_KEY,
  getConversation,
  loadConversations,
  migrateLegacyChatSession,
  newConversationId,
  removeConversation,
  titleFromText,
  upsertConversation,
} from "./conversationStore";

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

function customerMessage(content: string, id = "msg-1"): ChatMessage {
  return { id, role: "customer", content, timestamp: "2026-09-01T00:00:00.000Z" };
}

function workspaceTurn(request: string, conversationId: string): ConversationTurn {
  const response: AgentResponse = {
    conversation_id: conversationId,
    agent_run_id: `run-${conversationId}`,
    message: "A bounded operator response.",
    intent: "policy_question",
    request_type: "read",
    tool_call: null,
    pending_action: null,
    error_category: null,
    failure_category: null,
    degraded_components: [],
    recovery_action: null,
    execution_mode: "recorded_replay",
    provider: "recorded_evidence",
    model: null,
    fallback_message: null,
  };
  return { request, response };
}

describe("conversationStore", () => {
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

  it("creates prefixed conversation ids", () => {
    expect(newConversationId("chat")).toMatch(/^chat-/);
    expect(newConversationId("operator")).toMatch(/^operator-/);
  });

  it("trims titles to the first 48 characters", () => {
    expect(titleFromText("  hello   world  ")).toBe("hello world");
    const long = "I received a damaged product and want a refund for order 1 immediately please";
    const title = titleFromText(long);
    expect(title.length).toBeLessThanOrEqual(TITLE_MAX_CHARS);
    expect(title).toBe(long.slice(0, TITLE_MAX_CHARS).trimEnd());
    expect(titleFromText("   ")).toBe("");
  });

  it("does not persist an empty conversation", () => {
    expect(upsertConversation(CHAT_CONVERSATIONS_KEY, {
      conversationId: "chat-empty",
      customerId: 1,
      messages: [],
      lastRunId: null,
    })).toEqual([]);
    expect(loadConversations(CHAT_CONVERSATIONS_KEY)).toEqual([]);

    expect(upsertConversation(WORKSPACE_CONVERSATIONS_KEY, {
      conversationId: "operator-empty",
      customerId: 1,
      turns: [],
      lastRunId: null,
    })).toEqual([]);
    expect(loadConversations(WORKSPACE_CONVERSATIONS_KEY)).toEqual([]);
  });

  it("upserts a chat conversation and reads it back", () => {
    upsertConversation(CHAT_CONVERSATIONS_KEY, {
      conversationId: "chat-abc",
      customerId: 2,
      messages: [customerMessage("I received a damaged product")],
      lastRunId: "run-1",
    });
    const loaded = loadConversations(CHAT_CONVERSATIONS_KEY);
    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toMatchObject({
      conversationId: "chat-abc",
      customerId: 2,
      title: "I received a damaged product",
      lastRunId: "run-1",
    });
    expect(getConversation(CHAT_CONVERSATIONS_KEY, "chat-abc")?.messages).toHaveLength(1);
  });

  it("keeps the newest 25 conversations and drops the oldest", () => {
    for (let index = 0; index < MAX_CONVERSATIONS + 1; index += 1) {
      upsertConversation(CHAT_CONVERSATIONS_KEY, {
        conversationId: `chat-${index}`,
        customerId: 1,
        messages: [customerMessage(`request ${index}`, `msg-${index}`)],
        updatedAt: new Date(1_700_000_000_000 + index * 1000).toISOString(),
      });
    }
    const loaded = loadConversations(CHAT_CONVERSATIONS_KEY);
    expect(loaded).toHaveLength(MAX_CONVERSATIONS);
    expect(loaded.find((item) => item.conversationId === "chat-0")).toBeUndefined();
    expect(loaded[0]?.conversationId).toBe(`chat-${MAX_CONVERSATIONS}`);
    expect(loaded[loaded.length - 1]?.conversationId).toBe("chat-1");
  });

  it("drops corrupt records and keeps valid ones", () => {
    localStorage.setItem(CHAT_CONVERSATIONS_KEY, JSON.stringify([
      { conversationId: "chat-good", customerId: 1, updatedAt: "2026-09-01T00:00:00.000Z", title: "Hello", messages: [customerMessage("Hello")], lastRunId: null },
      { conversationId: 12, messages: "nope" },
      null,
    ]));
    expect(loadConversations(CHAT_CONVERSATIONS_KEY).map((item) => item.conversationId)).toEqual(["chat-good"]);
  });

  it("removes a conversation from the browser store", () => {
    upsertConversation(CHAT_CONVERSATIONS_KEY, {
      conversationId: "chat-keep",
      customerId: 1,
      messages: [customerMessage("keep me")],
    });
    upsertConversation(CHAT_CONVERSATIONS_KEY, {
      conversationId: "chat-drop",
      customerId: 1,
      messages: [customerMessage("drop me")],
    });
    removeConversation(CHAT_CONVERSATIONS_KEY, "chat-drop");
    expect(getConversation(CHAT_CONVERSATIONS_KEY, "chat-drop")).toBeNull();
    expect(getConversation(CHAT_CONVERSATIONS_KEY, "chat-keep")?.title).toBe("keep me");
  });

  it("migrates a legacy sessionStorage chat into the local list", () => {
    sessionStorage.setItem(LEGACY_CHAT_SESSION_KEY, JSON.stringify({
      conversationId: "chat-legacy",
      customerId: 3,
      messages: [customerMessage("Please refund order 1")],
    }));
    const migrated = migrateLegacyChatSession();
    expect(migrated).toHaveLength(1);
    expect(migrated[0]).toMatchObject({
      conversationId: "chat-legacy",
      customerId: 3,
      title: "Please refund order 1",
    });
    expect(sessionStorage.getItem(LEGACY_CHAT_SESSION_KEY)).toBeNull();
    expect(migrateLegacyChatSession()).toHaveLength(1);
  });

  it("does not migrate an empty legacy session", () => {
    sessionStorage.setItem(LEGACY_CHAT_SESSION_KEY, JSON.stringify({
      conversationId: "chat-blank",
      customerId: 1,
      messages: [],
    }));
    expect(migrateLegacyChatSession()).toEqual([]);
    expect(sessionStorage.getItem(LEGACY_CHAT_SESSION_KEY)).toBeNull();
  });

  it("preserves lastRunId when a later upsert omits it", () => {
    upsertConversation(WORKSPACE_CONVERSATIONS_KEY, {
      conversationId: "operator-1",
      customerId: 1,
      turns: [workspaceTurn("What is the refund policy?", "operator-1")],
      lastRunId: "run-keep",
    });
    upsertConversation(WORKSPACE_CONVERSATIONS_KEY, {
      conversationId: "operator-1",
      customerId: 1,
      turns: [workspaceTurn("What is the refund policy?", "operator-1")],
      lastRunId: null,
    });
    expect(getConversation(WORKSPACE_CONVERSATIONS_KEY, "operator-1")?.lastRunId).toBe("run-keep");
  });
});
