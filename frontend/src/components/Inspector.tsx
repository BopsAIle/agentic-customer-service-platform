import type { ReactNode } from "react";
import type { AgentRun } from "../types";
import { Panel } from "./Panel";

export function Inspector({ run }: { run: AgentRun | null }) {
  if (!run) return <Panel title="Agent inspector" eyebrow="Structured metadata"><Empty text="Run a request to open the inspector." /></Panel>;
  return <Panel title="Agent inspector" eyebrow="Structured metadata">
    <div className="grid grid-cols-2 gap-3 text-xs">
      <Metric label="Intent" value={run.intent} /><Metric label="Request type" value={run.request_type} /><Metric label="Status" value={run.status} /><Metric label="Duration" value={`${run.duration_ms.toFixed(1)} ms`} />
    </div>
    <div className="mt-5 space-y-2 text-xs"><Meta label="Conversation ID" value={run.conversation_id} /><Meta label="Agent run" value={run.run_id} /><Meta label="Trace ID" value={run.trace_id ?? "not exported"} /></div>
    <div className="mt-5"><div className="mb-2 text-[10px] font-bold uppercase tracking-[.2em] text-slate-500">Path</div><div className="flex flex-wrap items-center gap-2">{run.path.map((step, i) => <span key={`${step}-${i}`} className="flex items-center gap-2"><span className="rounded-md border border-line bg-ink px-2 py-1 text-[11px] text-slate-300">{step}</span>{i < run.path.length - 1 && <span className="text-mint/50">→</span>}</span>)}</div></div>
  </Panel>;
}

export function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-line bg-ink/60 p-3"><div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">{label}</div><div className="truncate font-mono text-xs text-mint">{value}</div></div>; }
function Meta({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4 border-b border-line/70 pb-2"><span className="text-slate-500">{label}</span><span className="max-w-[62%] truncate font-mono text-slate-300">{value}</span></div>; }
export function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed border-line p-5 text-center text-xs text-slate-500">{text}</div>; }
export function SectionLabel({ children }: { children: ReactNode }) { return <div className="mb-3 text-[10px] font-bold uppercase tracking-[.2em] text-slate-500">{children}</div>; }
