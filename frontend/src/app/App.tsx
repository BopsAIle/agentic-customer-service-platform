import { Activity, Bot, Command, LayoutDashboard, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ApiError, api, getApiAuthSnapshot, initializeApiAuth } from "../api/client";
import { Inspector } from "../components/Inspector";
import { Playground } from "../components/Playground";
import { ResiliencePanel } from "../components/ResiliencePanel";
import { SafetyDashboard } from "../components/SafetyDashboard";
import { SystemHealthStrip, type ApiReachability } from "../components/SystemHealth";
import { TraceTimeline } from "../components/TraceTimeline";
import { WorkspaceRail } from "../components/WorkspaceRail";
import { DataRow, MetricCard, StatusIndicator } from "../components/ui";
import type { AgentRun, ConversationTurn, Health, MemoryRecord } from "../types";
import type { AuthSnapshot } from "../auth/provider";

function AuthBoundary({ snapshot }: { snapshot: AuthSnapshot }) {
  const loading = snapshot.status === "loading";
  const message = loading ? "Establishing the operator authentication session…" : snapshot.status === "misconfigured" ? "Production authentication is not configured. Connect the console to an external identity or session provider before use." : snapshot.status === "unauthenticated" ? "Your operator session is missing or expired. Establish a session through the configured identity provider." : "Authentication is required to use the Operator Console.";
  return <main className="flex min-h-screen items-center justify-center px-6"><section className="surface max-w-xl p-8 text-center"><div className="eyebrow">Agent control plane</div><h1 className="section-title mt-2">{loading ? "Connecting authentication" : "Authentication required"}</h1><p className="mt-3 text-sm text-muted">{message}</p></section></main>;
}

function RunHeader({ run, conversationId }: { run: AgentRun | null; conversationId: string }) {
  const risk = run?.tools.reduce((max, tool) => Math.max(max, tool.risk_level ?? 0), 0) ?? 0;
  return <section className="run-header"><div className="flex flex-wrap items-start justify-between gap-5"><div className="flex items-start gap-3"><div className="brand-mark"><Command size={17} strokeWidth={1.8} aria-hidden="true" /></div><div><div className="eyebrow">AI agent control plane</div><h1 className="mt-1 text-xl font-semibold tracking-tight text-main">Operate the decision, not the model</h1><div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted"><span className="inline-flex items-center gap-1.5"><Activity size={13} aria-hidden="true" />{run ? `Run ${run.run_id.slice(0, 12)}` : "No selected run"}</span><span className="text-border">/</span><span className="font-mono">{conversationId}</span></div></div></div><div className="flex items-center gap-3"><StatusIndicator label={run?.status ?? "Ready"} tone={run?.status === "error" ? "danger" : run?.status === "waiting_confirmation" ? "warning" : "success"} /><span className="hidden text-xs text-muted sm:inline">Proposal → validation → authority</span></div></div><div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4"><MetricCard label="Intent" value={run?.intent ?? "—"} detail={run ? run.request_type.replace(/_/g, " ") : "Awaiting request"} /><MetricCard label="Customer" value={run ? `#${run.customer_id}` : "—"} detail="Authenticated scope" /><MetricCard label="Risk" value={run ? `Level ${risk}` : "—"} detail={risk > 1 ? "Confirmation boundary" : "No write risk"} /><MetricCard label="Trace" value={run?.trace_id ? "linked" : "—"} detail={run?.trace_id ? "Operator projection" : "Not exported"} /></div></section>;
}

export function App() {
  const [customerId, setCustomerId] = useState(1);
  const [conversationId] = useState(() => `operator-${crypto.randomUUID().slice(0, 8)}`);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [recentRuns, setRecentRuns] = useState<AgentRun[]>([]);
  const [memory, setMemory] = useState<MemoryRecord[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [apiReachability, setApiReachability] = useState<ApiReachability>("unknown");
  const [auth, setAuth] = useState<AuthSnapshot>(() => getApiAuthSnapshot());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"workspace" | "evidence">("workspace");

  useEffect(() => { initializeApiAuth().then(setAuth); }, []);
  useEffect(() => { if (auth.status !== "authenticated") return; api.health().then((value) => { setHealth(value); setApiReachability("reachable"); }).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) { setAuth(getApiAuthSnapshot()); setHealth(null); setApiReachability("unknown"); } else { setHealth(null); setApiReachability("unavailable"); } }); }, [auth.status]);
  useEffect(() => { if (auth.status !== "authenticated") return; api.memory(customerId).then(setMemory).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) setAuth(getApiAuthSnapshot()); else setMemory([]); }); }, [auth.status, customerId]);
  useEffect(() => { if (auth.status !== "authenticated") return; api.runs().then(setRecentRuns).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) setAuth(getApiAuthSnapshot()); else setRecentRuns([]); }); }, [auth.status]);

  const send = async (message: string) => { setBusy(true); setError(null); try { const response = await api.chat(conversationId, customerId, message); setTurns((current) => [...current, { request: message, response }]); const nextRun = await api.run(response.agent_run_id); setRun(nextRun); setRecentRuns((current) => [nextRun, ...current.filter((item) => item.run_id !== nextRun.run_id)].slice(0, 25)); setMemory(await api.memory(customerId)); const nextHealth = await api.health(); setHealth(nextHealth); setApiReachability("reachable"); } catch (caught) { if (caught instanceof ApiError && caught.status === 401) { setAuth(getApiAuthSnapshot()); setTurns([]); setRun(null); setMemory([]); setHealth(null); setApiReachability("unknown"); } else if (caught instanceof TypeError) { setHealth(null); setApiReachability("unavailable"); } setError(caught instanceof Error ? caught.message : "The operator API is unavailable."); } finally { setBusy(false); } };
  const selectRun = async (selected: AgentRun) => { setError(null); setRun(selected); setCustomerId(selected.customer_id); try { setRun(await api.run(selected.run_id)); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load the selected run."); } };
  const lastUpdated = useMemo(() => run ? new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—", [run]);
  if (auth.status !== "authenticated") return <AuthBoundary snapshot={auth} />;
  return <div className="min-h-screen"><header className="topbar"><div className="topbar-inner flex-wrap"><div className="flex items-center gap-3"><div className="brand-mark brand-mark-small"><Bot size={15} aria-hidden="true" /></div><span className="text-sm font-semibold tracking-[.12em] text-main">AGENTIC OPS</span><span className="hidden text-xs text-muted sm:inline">/ control plane</span></div><nav className="console-nav" aria-label="Console views"><button type="button" className={`console-nav-button ${view === "workspace" ? "console-nav-active" : ""}`} onClick={() => setView("workspace")}><LayoutDashboard size={14} aria-hidden="true" />Workspace</button><button type="button" className={`console-nav-button ${view === "evidence" ? "console-nav-active" : ""}`} onClick={() => setView("evidence")}><ShieldCheck size={14} aria-hidden="true" />Safety & evaluation</button></nav><div className="flex items-center gap-4"><span className="hidden text-xs text-muted xl:inline">source-bound operator view</span><StatusIndicator label="Authenticated" tone="success" compact /></div></div></header><main className="mx-auto max-w-[1760px] space-y-5 px-4 py-5 sm:px-6 lg:px-8">{view === "workspace" ? <><RunHeader run={run} conversationId={conversationId} /><div className="workspace-control-grid"><WorkspaceRail runs={recentRuns} selectedRunId={run?.run_id ?? null} currentConversationId={conversationId} onSelect={selectRun} /><Playground customerId={customerId} conversationId={conversationId} turns={turns} busy={busy} error={error} onCustomerChange={setCustomerId} onSend={send} /><Inspector run={run} memoryRecords={memory} /></div><div className="grid gap-5 xl:grid-cols-[1.15fr_1fr_1fr]"><TraceTimeline events={run?.trace ?? []} /><ResiliencePanel health={health} run={run} /><section className="surface p-5"><div className="eyebrow">Run context</div><h2 className="section-title mt-1">Correlation</h2><div className="mt-4 divide-y divide-border/70"><DataRow label="Last activity" value={lastUpdated} /><DataRow label="Conversation" value={conversationId} mono /><DataRow label="Scope" value={`customer #${customerId}`} /></div></section></div><SystemHealthStrip health={health} apiReachability={apiReachability} /></> : <SafetyDashboard />}</main><footer className="mx-auto max-w-[1760px] px-4 pb-8 text-[11px] text-muted sm:px-6 lg:px-8">Operator surface for debugging and demonstrations · prompts, raw payloads, and chain-of-thought are not displayed.</footer></div>;
}
