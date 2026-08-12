export type ToolEvent = {
  name: string;
  risk_level: number | null;
  status: string;
  duration_ms: number;
  result_fields: string[];
};

export type PolicyEvent = {
  action_id: string | null;
  tool_name: string;
  risk_level: number;
  outcome: string;
  reason_codes: string[];
};

export type RagDocument = {
  citation_id: string;
  title: string;
  section: string;
  source: string;
  score: number;
};

export type RetrievalMetadata = {
  backend: string;
  embedding_provider: string;
  reranker_enabled: boolean;
  retrieval_count: number;
  latency_seconds: number;
  fallback_status: string;
  hybrid: boolean;
  fusion_strategy: string;
  dense_candidate_count: number;
  sparse_candidate_count: number;
};

export type MemoryUsage = { item_count: number; keys: string[]; types: string[] };
export type TraceEvent = { name: string; status: string; duration_ms: number; timestamp: string };

export type AgentRun = {
  run_id: string;
  request_id: string;
  conversation_id: string;
  action_id: string | null;
  customer_id: number;
  intent: string;
  request_type: string;
  status: string;
  started_at: string;
  duration_ms: number;
  trace_id: string | null;
  path: string[];
  failure_category: string | null;
  degraded_components: string[];
  recovery_action: string | null;
  memory: MemoryUsage;
  tools: ToolEvent[];
  policy: PolicyEvent[];
  rag_documents: RagDocument[];
  retrieval_metadata: RetrievalMetadata;
  trace: TraceEvent[];
};

export type MemoryRecord = {
  id: number;
  customer_id: number;
  memory_type: string;
  normalized_key: string;
  source: string;
  status: string;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
};

export type HealthStatus = "ready" | "not_ready";
export type ComponentHealthStatus =
  | "healthy"
  | "unavailable"
  | "incompatible"
  | "configured"
  | "not_configured"
  | "not_probed";
export type Health = {
  status: HealthStatus;
  components: { name: string; status: ComponentHealthStatus; detail: string }[];
};

export type AgentResponse = {
  conversation_id: string;
  agent_run_id: string;
  message: string;
  intent: string;
  request_type: string;
  error_category: string | null;
  failure_category: string | null;
  degraded_components: string[];
  recovery_action: string | null;
  tool_call?: { name: string; status: string; result?: Record<string, unknown> | null } | null;
  pending_action?: { action_id?: string; tool_name?: string; status?: string } | null;
};

export type ConversationTurn = {
  request: string;
  response: AgentResponse;
};
