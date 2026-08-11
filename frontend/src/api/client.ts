import type { AgentResponse, AgentRun, Health, MemoryRecord } from "../types";

const base = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const api = {
  chat: (conversationId: string, customerId: number, message: string) =>
    request<AgentResponse>("/agent/chat", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, customer_id: customerId, message }),
    }),
  run: (runId: string) => request<AgentRun>(`/ui/agent-runs/${runId}`),
  memory: (customerId: number) => request<MemoryRecord[]>(`/ui/memory/${customerId}`),
  health: () => request<Health>("/ui/system-health"),
};
