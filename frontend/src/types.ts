export type ToolEvent = {
  name: string;
  risk_level: number | null;
  status: string;
  duration_ms: number;
  result_fields: string[];
};

export type PolicyEvent = {
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

export type MemoryUsage = { item_count: number; keys: string[]; types: string[] };
export type TraceEvent = { name: string; status: string; duration_ms: number; timestamp: string };

export type AgentRun = {
  run_id: string;
  conversation_id: string;
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
  trace: TraceEvent[];
};

export type MemoryRecord = {
  id: number;
  memory_type: string;
  normalized_key: string;
  content: string;
  status: string;
  created_at: string;
  expires_at: string | null;
};

export type Health = {
  status: string;
  components: { name: string; status: string; detail: string }[];
};

export type AgentResponse = {
  conversation_id: string;
  agent_run_id: string;
  message: string;
  intent: string;
  request_type: string;
  failure_category: string | null;
  degraded_components: string[];
  recovery_action: string | null;
};

export type ConversationTurn = {
  request: string;
  response: AgentResponse;
};
