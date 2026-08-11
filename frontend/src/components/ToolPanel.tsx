import { Clock3, Wrench } from "lucide-react";
import type { ToolEvent } from "../types";
import { Badge, EmptyState, Panel, SectionHeader, Timeline } from "./ui";

export function ToolPanel({ tools, embedded = false }: { tools: ToolEvent[]; embedded?: boolean }) {
  const content = tools.length === 0 ? <EmptyState title="No tool activity" description="This run did not execute a business tool." icon={Wrench} /> : <Timeline items={tools.map((tool) => ({ title: tool.name, subtitle: <span className="inline-flex items-center gap-2"><Badge tone={tool.status === "executed" ? "success" : "warning"}>Risk {tool.risk_level ?? "—"}</Badge><span>{tool.status}</span></span>, meta: <span className="inline-flex items-center gap-1"><Clock3 size={12} aria-hidden="true" />{tool.duration_ms.toFixed(1)} ms</span>, tone: tool.status === "executed" ? "success" : "warning" }))} />;
  return embedded ? <div>{content}</div> : <Panel title="Tool execution" eyebrow="Execution timeline"><SectionHeader title="Business tools" description="Risk and status only; sensitive arguments are omitted." />{content}</Panel>;
}
