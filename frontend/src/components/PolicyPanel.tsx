import { CheckCircle2, ShieldCheck } from "lucide-react";
import type { PolicyEvent } from "../types";
import { Badge, EmptyState, Panel, SectionHeader } from "./ui";

export function PolicyPanel({ events, embedded = false }: { events: PolicyEvent[]; embedded?: boolean }) {
  const content = events.length === 0 ? <EmptyState title="No policy decision" description="Policy evaluation will appear when a tool is selected." icon={ShieldCheck} /> : <div className="space-y-3">{events.map((event, index) => <div className="decision-block" key={`${event.tool_name}-${index}`}><div className="flex items-start justify-between gap-3"><div><div className="eyebrow">Decision</div><div className="mt-1 text-sm font-semibold capitalize text-main">{event.outcome.replace(/_/g, " ")}</div></div><Badge tone={event.outcome === "allow" ? "success" : event.outcome === "deny" ? "danger" : "warning"}>Risk {event.risk_level}</Badge></div><div className="mt-4 space-y-2">{event.reason_codes.slice(0, 4).map((code) => <div className="flex items-center gap-2 text-xs capitalize text-muted" key={code}><CheckCircle2 size={14} className="text-success" aria-hidden="true" />{code.replace(/_/g, " ")}</div>)}</div></div>)}</div>;
  return embedded ? <div>{content}</div> : <Panel title="Policy evaluation" eyebrow="Authorization boundary"><SectionHeader title="Deterministic policy" description="Structured outcomes and validation checkpoints." />{content}</Panel>;
}
