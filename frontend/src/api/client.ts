import type { AgentResponse, AgentRun, Health, MemoryRecord } from "../types";

const base = import.meta.env.VITE_API_BASE ?? "";
let bearerToken: string | null = import.meta.env.VITE_DEMO_AUTH_TOKEN || null;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function setApiBearerToken(token: string | null): void {
  bearerToken = token?.trim() || null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (bearerToken) headers.set("Authorization", `Bearer ${bearerToken}`);
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const message =
      response.status === 401
        ? "Authentication failed. Check the configured operator credential."
        : response.status === 403
          ? "The authenticated operator is not permitted to perform this request."
          : `Request failed (${response.status}).`;
    throw new ApiError(message, response.status);
  }
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
