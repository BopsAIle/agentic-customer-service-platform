import type { PolicyEvent } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function PolicyPanel({ events }: { events: PolicyEvent[] }) { return <Panel title="Policy evaluation" eyebrow="Authorization boundary">{events.length === 0 ? <Empty text="No policy decision recorded for this run." /> : <div className="space-y-3">{events.map((event, i) => <div key={`${event.tool_name}-${i}`} className="rounded-xl border border-line bg-ink/60 p-4"><div className="flex items-center justify-between"><span className="font-mono text-sm text-white">{event.tool_name}</span><Badge tone={event.outcome === "allow" ? "mint" : "amber"}>{event.outcome}</Badge></div><div className="mt-3 flex gap-2"><Badge>Risk {event.risk_level}</Badge>{event.reason_codes.map((code) => <Badge key={code} tone="slate">{code}</Badge>)}</div></div>)}</div>}</Panel>; }
