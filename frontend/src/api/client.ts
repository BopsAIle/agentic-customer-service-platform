import type { AgentResponse, AgentRun, Health, MemoryRecord } from "../types";
import {
  createConfiguredAuthProvider,
  type AuthProvider,
  type AuthSnapshot,
} from "../auth/provider";

const base = import.meta.env.VITE_API_BASE ?? "";
let authProvider: AuthProvider = createConfiguredAuthProvider();

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function setApiAuthProvider(provider: AuthProvider): void {
  authProvider = provider;
}

export function getApiAuthProvider(): AuthProvider {
  return authProvider;
}

export function getApiAuthSnapshot(): AuthSnapshot {
  return authProvider.getSnapshot();
}

export async function initializeApiAuth(): Promise<AuthSnapshot> {
  return authProvider.initialize();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = authProvider.getSnapshot();
  if (auth.status !== "authenticated") {
    const message =
      auth.status === "misconfigured"
        ? "Production authentication is not configured."
        : "Authentication is required to use the Operator Console.";
    throw new ApiError(message, auth.status === "unauthenticated" ? 401 : 0);
  }
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const credential = authProvider.getAccessCredential();
  if (credential) headers.set("Authorization", `Bearer ${credential}`);
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers,
    credentials: authProvider.usesCookieSession() ? "include" : init?.credentials,
  });
  if (!response.ok) {
    if (response.status === 401) authProvider.clearCredential();
    const message =
      response.status === 401
        ? "Authentication session is missing or expired."
        : response.status === 403
          ? "The authenticated operator is not permitted to perform this request."
          : `Request failed (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  runs: (limit = 25) => request<AgentRun[]>(`/ui/agent-runs?limit=${limit}`),
  chat: (conversationId: string, customerId: number, message: string) =>
    request<AgentResponse>("/agent/chat", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, customer_id: customerId, message }),
    }),
  run: (runId: string) => request<AgentRun>(`/ui/agent-runs/${runId}`),
  memory: (customerId: number) => request<MemoryRecord[]>(`/ui/memory/${customerId}`),
  health: () => request<Health>("/ui/system-health"),
};
