import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { MemoryPanel } from "../components/MemoryPanel";
import { Inspector } from "../components/Inspector";
import { Playground } from "../components/Playground";
import { PolicyPanel } from "../components/PolicyPanel";
import { RagPanel } from "../components/RagPanel";
import { ResiliencePanel } from "../components/ResiliencePanel";
import { ToolPanel } from "../components/ToolPanel";
import { TraceTimeline } from "../components/TraceTimeline";
import type { AgentRun, ConversationTurn, Health, MemoryRecord } from "../types";

export function App() {
  const [customerId, setCustomerId] = useState(1);
  const [conversationId] = useState(() => `operator-${crypto.randomUUID().slice(0, 8)}`);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [memory, setMemory] = useState<MemoryRecord[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, []);
  useEffect(() => { api.memory(customerId).then(setMemory).catch(() => setMemory([])); }, [customerId]);

  const send = async (message: string) => {
    setBusy(true); setError(null);
    try {
      const response = await api.chat(conversationId, customerId, message);
      setTurns((current) => [...current, { request: message, response }]);
      const nextRun = await api.run(response.agent_run_id);
      setRun(nextRun);
      const nextMemory = await api.memory(customerId);
      setMemory(nextMemory);
      setHealth(await api.health());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The operator API is unavailable."); }
    finally { setBusy(false); }
  };
  const title = useMemo(() => run ? `${run.intent} · ${run.status}` : "Live agent workspace", [run]);
  return <div className="min-h-screen bg-ink text-slate-200"><header className="border-b border-line/80 bg-ink/90"><div className="mx-auto flex max-w-[1600px] items-center justify-between px-6 py-5"><div><div className="flex items-center gap-3"><div className="h-3 w-3 rounded-full bg-mint shadow-[0_0_18px_rgba(120,230,196,.9)]" /><span className="text-sm font-bold tracking-[.18em] text-white">AGENTIC OPS</span></div><p className="mt-2 text-xs text-slate-500">Operator console · {title}</p></div><div className="hidden text-right md:block"><div className="text-[10px] uppercase tracking-[.2em] text-slate-500">Transparency boundary</div><div className="mt-1 text-xs text-mint">Metadata only · no chain-of-thought</div></div></div></header><main className="mx-auto grid max-w-[1600px] gap-5 px-6 py-6 xl:grid-cols-[minmax(420px,1.1fr)_minmax(440px,.9fr)]"><div className="space-y-5"><Playground customerId={customerId} conversationId={conversationId} turns={turns} busy={busy} error={error} onCustomerChange={setCustomerId} onSend={send} /><Inspector run={run} /><ResiliencePanel health={health} run={run} /></div><div className="space-y-5"><div className="grid gap-5 md:grid-cols-2"><ToolPanel tools={run?.tools ?? []} /><PolicyPanel events={run?.policy ?? []} /></div><RagPanel documents={run?.rag_documents ?? []} /><MemoryPanel usage={run?.memory ?? { item_count: 0, keys: [], types: [] }} records={memory} /><TraceTimeline events={run?.trace ?? []} /></div></main><footer className="mx-auto max-w-[1600px] px-6 pb-8 text-[11px] text-slate-600">For support operators and demonstrations. Authentication and authorization are deployment concerns.</footer></div>;
}
