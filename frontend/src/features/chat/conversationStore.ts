import type { ConversationTurn } from "../../types";
import type { ChatMessage } from "./MessageBubble";

export const CHAT_CONVERSATIONS_KEY = "agentic-ops.chat.conversations.v1";
export const WORKSPACE_CONVERSATIONS_KEY = "agentic-ops.workspace.conversations.v1";
export const LEGACY_CHAT_SESSION_KEY = "agentic-ops.chat.session.v1";
export const MAX_CONVERSATIONS = 25;
export const TITLE_MAX_CHARS = 48;

export type ConversationPrefix = "chat" | "operator";

export type StoredChatConversation = {
  conversationId: string;
  customerId: number;
  updatedAt: string;
  title: string;
  messages: ChatMessage[];
  lastRunId: string | null;
};

export type StoredWorkspaceConversation = {
  conversationId: string;
  customerId: number;
  updatedAt: string;
  title: string;
  turns: ConversationTurn[];
  lastRunId: string | null;
};

export type StoredConversation = StoredChatConversation | StoredWorkspaceConversation;

export type ConversationUpsert = {
  conversationId: string;
  customerId: number;
  lastRunId?: string | null;
  updatedAt?: string;
  title?: string;
  messages?: ChatMessage[];
  turns?: ConversationTurn[];
};

type BrowserStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function browserStorage(kind: "local" | "session"): BrowserStorage | undefined {
  try {
    const bag = globalThis as typeof globalThis & { localStorage?: BrowserStorage; sessionStorage?: BrowserStorage };
    return kind === "local" ? bag.localStorage : bag.sessionStorage;
  } catch {
    return undefined;
  }
}

function readItem(kind: "local" | "session", key: string): string | null {
  try {
    return browserStorage(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeItem(kind: "local" | "session", key: string, value: string): void {
  try {
    browserStorage(kind)?.setItem(key, value);
  } catch {
    /* persistence is best effort */
  }
}

function deleteItem(kind: "local" | "session", key: string): void {
  try {
    browserStorage(kind)?.removeItem(key);
  } catch {
    /* persistence is best effort */
  }
}

export function newConversationId(prefix: ConversationPrefix): string {
  const id = globalThis.crypto?.randomUUID?.() ?? Date.now().toString(36);
  return `${prefix}-${id.slice(0, 8)}`;
}

export function titleFromText(text: string): string {
  const collapsed = text.trim().replace(/\s+/g, " ");
  if (!collapsed) return "";
  if (collapsed.length <= TITLE_MAX_CHARS) return collapsed;
  return collapsed.slice(0, TITLE_MAX_CHARS).trimEnd();
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (typeof value !== "object" || value === null) return false;
  const message = value as Partial<ChatMessage>;
  return typeof message.id === "string"
    && (message.role === "customer" || message.role === "agent")
    && typeof message.content === "string"
    && typeof message.timestamp === "string";
}

function isTurn(value: unknown): value is ConversationTurn {
  if (typeof value !== "object" || value === null) return false;
  const turn = value as { request?: unknown; response?: unknown };
  if (typeof turn.request !== "string" || typeof turn.response !== "object" || turn.response === null) return false;
  const response = turn.response as { agent_run_id?: unknown; message?: unknown; conversation_id?: unknown };
  return typeof response.agent_run_id === "string" && typeof response.message === "string" && typeof response.conversation_id === "string";
}

function parseChatConversation(value: unknown): StoredChatConversation | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Partial<StoredChatConversation>;
  if (typeof candidate.conversationId !== "string" || !Array.isArray(candidate.messages)) return null;
  const messages = candidate.messages.filter(isChatMessage);
  if (messages.length === 0) return null;
  const title = typeof candidate.title === "string" && candidate.title.trim()
    ? candidate.title
    : titleFromText(messages.find((message) => message.role === "customer")?.content ?? messages[0]?.content ?? "");
  if (!title) return null;
  return {
    conversationId: candidate.conversationId,
    customerId: typeof candidate.customerId === "number" ? candidate.customerId : 1,
    updatedAt: typeof candidate.updatedAt === "string" ? candidate.updatedAt : new Date(0).toISOString(),
    title,
    messages,
    lastRunId: typeof candidate.lastRunId === "string" ? candidate.lastRunId : null,
  };
}

function parseWorkspaceConversation(value: unknown): StoredWorkspaceConversation | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Partial<StoredWorkspaceConversation>;
  if (typeof candidate.conversationId !== "string" || !Array.isArray(candidate.turns)) return null;
  const turns = candidate.turns.filter(isTurn);
  if (turns.length === 0) return null;
  const title = typeof candidate.title === "string" && candidate.title.trim()
    ? candidate.title
    : titleFromText(turns[0]?.request ?? "");
  if (!title) return null;
  return {
    conversationId: candidate.conversationId,
    customerId: typeof candidate.customerId === "number" ? candidate.customerId : 1,
    updatedAt: typeof candidate.updatedAt === "string" ? candidate.updatedAt : new Date(0).toISOString(),
    title,
    turns,
    lastRunId: typeof candidate.lastRunId === "string" ? candidate.lastRunId : null,
  };
}

function parseRecord(key: string, value: unknown): StoredConversation | null {
  return key === WORKSPACE_CONVERSATIONS_KEY ? parseWorkspaceConversation(value) : parseChatConversation(value);
}

function isWorkspaceKey(key: string): key is typeof WORKSPACE_CONVERSATIONS_KEY {
  return key === WORKSPACE_CONVERSATIONS_KEY;
}

export function loadConversations(key: typeof CHAT_CONVERSATIONS_KEY): StoredChatConversation[];
export function loadConversations(key: typeof WORKSPACE_CONVERSATIONS_KEY): StoredWorkspaceConversation[];
export function loadConversations(key: string): StoredConversation[];
export function loadConversations(key: string): StoredConversation[] {
  const raw = readItem("local", key);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => parseRecord(key, item))
      .filter((item): item is StoredConversation => item !== null)
      .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
  } catch {
    return [];
  }
}

export function getConversation(key: typeof CHAT_CONVERSATIONS_KEY, id: string): StoredChatConversation | null;
export function getConversation(key: typeof WORKSPACE_CONVERSATIONS_KEY, id: string): StoredWorkspaceConversation | null;
export function getConversation(key: string, id: string): StoredConversation | null;
export function getConversation(key: string, id: string): StoredConversation | null {
  return loadConversations(key).find((item) => item.conversationId === id) ?? null;
}

function persist(key: string, records: StoredConversation[]): void {
  writeItem("local", key, JSON.stringify(records));
}

export function upsertConversation(key: string, input: ConversationUpsert): StoredConversation[] {
  const existingList = loadConversations(key);
  const existing = existingList.find((item) => item.conversationId === input.conversationId) ?? null;
  const lastRunId = input.lastRunId ?? existing?.lastRunId ?? null;
  const updatedAt = input.updatedAt ?? new Date().toISOString();

  let nextRecord: StoredConversation | null = null;
  if (isWorkspaceKey(key)) {
    const turns = (input.turns ?? (existing && "turns" in existing ? existing.turns : [])).filter(isTurn);
    if (turns.length === 0) return existingList;
    const title = titleFromText(input.title ?? turns[0]?.request ?? "");
    if (!title) return existingList;
    nextRecord = {
      conversationId: input.conversationId,
      customerId: input.customerId,
      updatedAt,
      title,
      turns,
      lastRunId,
    };
  } else {
    const messages = (input.messages ?? (existing && "messages" in existing ? existing.messages : [])).filter(isChatMessage);
    if (messages.length === 0) return existingList;
    const title = titleFromText(
      input.title
        ?? messages.find((message) => message.role === "customer")?.content
        ?? messages[0]?.content
        ?? "",
    );
    if (!title) return existingList;
    nextRecord = {
      conversationId: input.conversationId,
      customerId: input.customerId,
      updatedAt,
      title,
      messages,
      lastRunId,
    };
  }

  const next = [nextRecord, ...existingList.filter((item) => item.conversationId !== input.conversationId)]
    .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))
    .slice(0, MAX_CONVERSATIONS);
  persist(key, next);
  return next;
}

export function removeConversation(key: string, id: string): StoredConversation[] {
  const next = loadConversations(key).filter((item) => item.conversationId !== id);
  persist(key, next);
  return next;
}

export function migrateLegacyChatSession(): StoredChatConversation[] {
  const current = loadConversations(CHAT_CONVERSATIONS_KEY);
  const raw = readItem("session", LEGACY_CHAT_SESSION_KEY);
  if (!raw) return current;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      const candidate = parsed as { conversationId?: unknown; customerId?: unknown; messages?: unknown };
      if (typeof candidate.conversationId === "string" && Array.isArray(candidate.messages)) {
        const messages = candidate.messages.filter(isChatMessage);
        if (messages.length > 0) {
          upsertConversation(CHAT_CONVERSATIONS_KEY, {
            conversationId: candidate.conversationId,
            customerId: typeof candidate.customerId === "number" ? candidate.customerId : 1,
            messages,
            lastRunId: null,
          });
        }
      }
    }
  } catch {
    /* ignore corrupt legacy sessions */
  }
  deleteItem("session", LEGACY_CHAT_SESSION_KEY);
  return loadConversations(CHAT_CONVERSATIONS_KEY);
}
