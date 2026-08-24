import { Clock3, Wrench } from "lucide-react";
import type { ToolEvent } from "../types";
import { Badge, EmptyState, Panel, SectionHeader, Timeline } from "./ui";

function projectedStatus(status: string): { label: string; tone: "success" | "warning" | "danger" } {
  if (status === "completed" || status === "executed") return { label: "Completed", tone: "success" };
  if (status === "failed_during_execution" || status === "failed") return { label: "Failed during execution", tone: "danger" };
  return { label: "Blocked before execution", tone: "warning" };
}

export function ToolPanel({ tools, embedded = false }: { tools: ToolEvent[]; embedded?: boolean }) {
  const content = tools.length === 0 ? <EmptyState title="No tool activity" description="This run did not execute a business tool." icon={Wrench} /> : <Timeline items={tools.map((tool) => { const status = projectedStatus(tool.status); return { title: tool.name, subtitle: <span className="inline-flex items-center gap-2"><Badge tone={status.tone}>Risk {tool.risk_level ?? "—"}</Badge><span>{status.label}</span></span>, meta: <span className="inline-flex items-center gap-1"><Clock3 size={12} aria-hidden="true" />{tool.duration_ms.toFixed(1)} ms</span>, tone: status.tone }; })} />;
  return embedded ? <div>{content}</div> : <Panel title="Tool execution" eyebrow="Execution timeline"><SectionHeader title="Business tools" description="Risk and status only; sensitive arguments are omitted." />{content}</Panel>;
}
