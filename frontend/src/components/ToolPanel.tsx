import type { ToolEvent } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function ToolPanel({ tools }: { tools: ToolEvent[] }) { return <Panel title="Tool execution" eyebrow="Bounded actions">{tools.length === 0 ? <Empty text="No tool execution in this run." /> : <div className="space-y-3">{tools.map((tool, i) => <div key={`${tool.name}-${i}`} className="rounded-xl border border-line bg-ink/60 p-4"><div className="flex items-center justify-between"><span className="font-mono text-sm text-white">{tool.name}</span><Badge tone={tool.status === "executed" ? "mint" : "amber"}>{tool.status}</Badge></div><div className="mt-3 flex gap-2"><Badge tone="slate">Risk {tool.risk_level ?? "—"}</Badge><Badge tone="slate">{tool.duration_ms.toFixed(1)} ms</Badge></div>{tool.result_fields.length > 0 && <div className="mt-3 text-xs text-slate-500">Result metadata: {tool.result_fields.join(", ")}</div>}</div>)}</div>}</Panel>; }
