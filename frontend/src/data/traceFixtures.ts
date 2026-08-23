import type { AgentRun, TraceEvent } from "../types";

export type RecordedTraceMetadata = {
  durationMs: number;
  evidenceCount: number;
  owner: string;
  source: "observed" | "recorded_fixture" | "not_recorded";
};

type FixtureDefinition = Omit<RecordedTraceMetadata, "source">;

// These values are deterministic presentation fixtures. If a run contains real
// event timing, the observed values take precedence over this fallback layer.
const FIXTURE_METADATA: Record<string, FixtureDefinition> = {
  request: { durationMs: 12, evidenceCount: 1, owner: "Request gateway" },
  intent: { durationMs: 28, evidenceCount: 1, owner: "Agent orchestration" },
  memory: { durationMs: 42, evidenceCount: 1, owner: "Memory subsystem" },
  context: { durationMs: 42, evidenceCount: 2, owner: "Context assembly" },
  rag: { durationMs: 180, evidenceCount: 1, owner: "Retrieval subsystem" },
  grounding: { durationMs: 65, evidenceCount: 2, owner: "Grounding validator" },
  target: { durationMs: 24, evidenceCount: 1, owner: "Decision compiler" },
  policy: { durationMs: 20, evidenceCount: 5, owner: "Policy engine" },
  confirmation: { durationMs: 16, evidenceCount: 1, owner: "Confirmation gate" },
  execution: { durationMs: 0, evidenceCount: 0, owner: "Execution authority" },
};

function observedMetadata(stageId: string, events: TraceEvent[]): RecordedTraceMetadata | null {
  if (events.length === 0) return null;
  const hasObservedTiming = events.some((event) => event.duration_ms > 0);
  const hasObservedMetadata = events.some((event) => Boolean(event.metadata && (event.metadata.owner || event.metadata.evidence_count)));
  if (!hasObservedTiming && !hasObservedMetadata) return null;
  return {
    durationMs: events.reduce((sum, event) => sum + event.duration_ms, 0),
    evidenceCount: events.reduce((sum, event) => sum + (event.metadata?.evidence_count as number || 0), 0),
    owner: events[0]?.metadata?.owner?.toString() || "Runtime projection",
    source: "observed",
  };
}

export function traceMetadata(stageId: string, run: AgentRun, events: TraceEvent[]): RecordedTraceMetadata {
  const observed = observedMetadata(stageId, events);
  if (observed) {
    return {
      ...observed,
      evidenceCount: observed.evidenceCount || evidenceCountFor(stageId, run),
    };
  }
  const fixture = FIXTURE_METADATA[stageId];
  if (!fixture) return { durationMs: 0, evidenceCount: 0, owner: "Not recorded", source: "not_recorded" };
  return { ...fixture, evidenceCount: evidenceCountFor(stageId, run, fixture.evidenceCount), source: "recorded_fixture" };
}

function evidenceCountFor(stageId: string, run: AgentRun, fallback = 0): number {
  if (stageId === "memory") return run.memory.items_used ?? run.memory.retrieved_count ?? run.memory.item_count;
  if (stageId === "rag") return run.rag_documents.length;
  if (stageId === "context") return (run.memory.items_used ?? run.memory.retrieved_count ?? run.memory.item_count) + run.rag_documents.length;
  if (stageId === "proposal") return run.proposal ? 1 : fallback;
  if (stageId === "policy") return run.policy.length ? 5 : 0;
  if (stageId === "target") return run.evidence.target_validation.status !== "not_recorded" ? 1 : 0;
  if (stageId === "confirmation") return run.evidence.confirmation.required ? 1 : 0;
  if (stageId === "grounding") return run.rag_documents.length || fallback;
  return fallback;
}

export function formatTraceDuration(metadata: RecordedTraceMetadata): string {
  if (metadata.source === "not_recorded") return "Not recorded";
  return `${metadata.durationMs.toFixed(0)} ms`;
}
