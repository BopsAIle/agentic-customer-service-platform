import type { TraceEvent } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function TraceTimeline({ events }: { events: TraceEvent[] }) { return <Panel title="Trace timeline" eyebrow="OpenTelemetry projection">{events.length === 0 ? <Empty text="No trace events available." /> : <div className="relative space-y-3 pl-5 before:absolute before:bottom-2 before:left-[6px] before:top-2 before:w-px before:bg-line">{events.map((event, i) => <div key={`${event.name}-${i}`} className="relative flex items-center justify-between gap-3"><span className="absolute -left-[18px] h-2 w-2 rounded-full bg-mint shadow-[0_0_12px_rgba(120,230,196,.8)]" /><span className="font-mono text-xs text-slate-300">{event.name}</span><Badge tone={event.status === "ok" ? "mint" : "amber"}>{event.duration_ms.toFixed(1)} ms</Badge></div>)}</div>}</Panel>; }
