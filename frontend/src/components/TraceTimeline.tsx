import { Activity, Clock3 } from "lucide-react";
import type { TraceEvent } from "../types";
import { EmptyState, Panel, SectionHeader, Timeline } from "./ui";

export function TraceTimeline({ events, embedded = false }: { events: TraceEvent[]; embedded?: boolean }) {
  const content = events.length === 0 ? <EmptyState title="No trace available" description="Run an agent request to generate execution data." icon={Activity} /> : <Timeline items={events.map((event) => ({ title: event.name.replace(/_/g, " "), subtitle: new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }), meta: <span className="inline-flex items-center gap-1"><Clock3 size={12} aria-hidden="true" />{event.duration_ms.toFixed(1)} ms</span>, tone: event.status === "ok" ? "success" : "danger" }))} />;
  return embedded ? <div>{content}</div> : <Panel title="Trace timeline" eyebrow="OpenTelemetry projection"><SectionHeader title="Execution events" description="Bounded event metadata; no prompts or hidden reasoning." />{content}</Panel>;
}
