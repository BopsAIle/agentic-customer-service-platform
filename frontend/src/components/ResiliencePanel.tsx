import type { Health, AgentRun } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function ResiliencePanel({ health, run }: { health: Health | null; run: AgentRun | null }) { const components = health?.components ?? []; return <Panel title="System status" eyebrow="Failure hardening"><div className="grid grid-cols-2 gap-2">{components.map((component) => <div key={component.name} className="rounded-xl border border-line bg-ink/60 p-3"><div className="flex items-center justify-between text-xs text-slate-300"><span>{component.name}</span><Badge tone={component.status === "degraded" ? "amber" : "mint"}>{component.status}</Badge></div><div className="mt-2 text-[11px] text-slate-600">{component.detail}</div></div>)}</div>{run?.failure_category && <div className="mt-4 rounded-xl border border-amber/20 bg-amber/5 p-3 text-xs text-amber"><div className="font-semibold">Recent recovery</div><div className="mt-1">{run.failure_category} · {run.recovery_action ?? "safe failure"}</div></div>}{!health && !run && <Empty text="Health and recovery data appear after the first run." />}</Panel>; }
