import { Activity, Beaker, Bot, Command, Compass, LayoutDashboard, MessageSquareText, Network, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, getApiAuthSnapshot, initializeApiAuth } from "../api/client";
import { Inspector } from "../components/Inspector";
import { AgentPlayground } from "../components/AgentPlayground";
import { ArchitectureOverview } from "../components/ArchitectureOverview";
import { DemoShowcase } from "../components/DemoShowcase";
import { OverviewDashboard } from "../components/OverviewDashboard";
import { Playground } from "../components/Playground";
import { ResiliencePanel } from "../components/ResiliencePanel";
import { RunInvestigationPage } from "../components/RunInvestigationPage";
import { SafetyDashboard } from "../components/SafetyDashboard";
import { SystemHealthStrip, type ApiReachability } from "../components/SystemHealth";
import { TraceDashboard } from "../components/TraceDashboard";
import { TraceTimeline } from "../components/TraceTimeline";
import { WorkspaceRail } from "../components/WorkspaceRail";
import { ChatWindow } from "../features/chat/ChatWindow";
import { getConversation, loadConversations, newConversationId, removeConversation, upsertConversation, WORKSPACE_CONVERSATIONS_KEY } from "../features/chat/conversationStore";
import { DataRow, MetricCard, StatusIndicator } from "../components/ui";
import type { AgentRun, ConversationTurn, DemoScenario, Health, MemoryRecord, PlaygroundExecution, PlaygroundHistoryItem, PlaygroundRequest, RuntimeConfig } from "../types";
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

type ConsoleView = "overview" | "chat" | "workspace" | "playground" | "evidence" | "traces" | "architecture" | "showcase";

function viewFromPath(pathname: string): ConsoleView {
  if (pathname === "/overview") return "overview";
  if (pathname === "/chat") return "chat";
  if (pathname === "/playground") return "playground";
  if (pathname === "/traces") return "traces";
  if (pathname === "/safety" || pathname === "/evidence") return "evidence";
  if (pathname === "/architecture") return "architecture";
  if (pathname === "/showcase") return "showcase";
  return "workspace";
}

export function App() {
  const [customerId, setCustomerId] = useState(() => loadConversations(WORKSPACE_CONVERSATIONS_KEY)[0]?.customerId ?? 1);
  const [conversationId, setConversationId] = useState(() => loadConversations(WORKSPACE_CONVERSATIONS_KEY)[0]?.conversationId ?? newConversationId("operator"));
  const [turns, setTurns] = useState<ConversationTurn[]>(() => loadConversations(WORKSPACE_CONVERSATIONS_KEY)[0]?.turns ?? []);
  const [workspaceConversations, setWorkspaceConversations] = useState(() => loadConversations(WORKSPACE_CONVERSATIONS_KEY));
  const [run, setRun] = useState<AgentRun | null>(null);
  const [recentRuns, setRecentRuns] = useState<AgentRun[]>([]);
  const [memory, setMemory] = useState<MemoryRecord[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [apiReachability, setApiReachability] = useState<ApiReachability>("unknown");
  const [auth, setAuth] = useState<AuthSnapshot>(() => getApiAuthSnapshot());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ConsoleView>(() => viewFromPath(window.location.pathname));
  const [playgroundExecution, setPlaygroundExecution] = useState<PlaygroundExecution | null>(null);
  const [playgroundRuns, setPlaygroundRuns] = useState<PlaygroundHistoryItem[]>([]);
  const [demoScenarios, setDemoScenarios] = useState<DemoScenario[]>([]);
  const [locationPath, setLocationPath] = useState(() => window.location.pathname);
  const [routeRunLoading, setRouteRunLoading] = useState(false);
  const [routeRunError, setRouteRunError] = useState<string | null>(null);

  const routeRunId = locationPath.startsWith("/runs/") ? decodeURIComponent(locationPath.slice("/runs/".length).split("/")[0]) : null;
  const conversationLoad = useRef(0);

  useEffect(() => { initializeApiAuth().then(setAuth); }, []);
  useEffect(() => { if (auth.status !== "authenticated") return; api.health().then((value) => { setHealth(value); setApiReachability("reachable"); }).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) { setAuth(getApiAuthSnapshot()); setHealth(null); setApiReachability("unknown"); } else { setHealth(null); setApiReachability("unavailable"); } }); api.runtimeConfig().then(setRuntimeConfig).catch(() => setRuntimeConfig(null)); }, [auth.status]);
  useEffect(() => { if (auth.status !== "authenticated") return; api.memory(customerId).then(setMemory).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) setAuth(getApiAuthSnapshot()); else setMemory([]); }); }, [auth.status, customerId]);
  useEffect(() => { if (auth.status !== "authenticated") return; api.runs().then((nextRuns) => setRecentRuns([...demoScenarios.map((scenario) => scenario.run), ...nextRuns.filter((run) => !demoScenarios.some((scenario) => scenario.run.run_id === run.run_id))])).catch((caught: unknown) => { if (caught instanceof ApiError && caught.status === 401) setAuth(getApiAuthSnapshot()); else setRecentRuns(demoScenarios.map((scenario) => scenario.run)); }); }, [auth.status, demoScenarios]);
  useEffect(() => { if (auth.status !== "authenticated") return; api.demoScenarios().then(setDemoScenarios).catch(() => setDemoScenarios([])); }, [auth.status]);
  useEffect(() => { const onPopState = () => { setLocationPath(window.location.pathname); setView(viewFromPath(window.location.pathname)); }; window.addEventListener("popstate", onPopState); return () => window.removeEventListener("popstate", onPopState); }, []);
  useEffect(() => { if (auth.status !== "authenticated" || !routeRunId) return; const recorded = demoScenarios.find((scenario) => scenario.run.run_id === routeRunId)?.run; if (routeRunId.startsWith("demo-") && !recorded) { setRouteRunLoading(true); return; } setRouteRunLoading(true); setRouteRunError(null); if (recorded) { setRun(recorded); setCustomerId(recorded.customer_id); setMemory([]); setRouteRunLoading(false); return; } api.run(routeRunId).then(async (nextRun) => { setRun(nextRun); setCustomerId(nextRun.customer_id); setMemory(await api.memory(nextRun.customer_id)); }).catch((caught: unknown) => { setRouteRunError(caught instanceof Error ? caught.message : "Investigation evidence unavailable"); }).finally(() => setRouteRunLoading(false)); }, [auth.status, demoScenarios, routeRunId]);
  useEffect(() => {
    if (turns.length === 0) return;
    upsertConversation(WORKSPACE_CONVERSATIONS_KEY, {
      conversationId,
      customerId,
      turns,
      lastRunId: turns[turns.length - 1]?.response.agent_run_id ?? null,
    });
    setWorkspaceConversations(loadConversations(WORKSPACE_CONVERSATIONS_KEY));
  }, [turns, conversationId, customerId]);

  const send = async (message: string) => { setBusy(true); setError(null); try { const response = await api.chat(conversationId, customerId, message); setTurns((current) => [...current, { request: message, response }]); const nextRun = await api.run(response.agent_run_id); setRun(nextRun); setRecentRuns((current) => [nextRun, ...current.filter((item) => item.run_id !== nextRun.run_id)].slice(0, 25)); setMemory(await api.memory(customerId)); const nextHealth = await api.health(); setHealth(nextHealth); setApiReachability("reachable"); } catch (caught) { if (caught instanceof ApiError && caught.status === 401) { setAuth(getApiAuthSnapshot()); setTurns([]); setRun(null); setMemory([]); setHealth(null); setApiReachability("unknown"); } else if (caught instanceof TypeError) { setHealth(null); setApiReachability("unavailable"); } setError(caught instanceof Error ? caught.message : "The operator API is unavailable."); } finally { setBusy(false); } };
  const runPlayground = async (request: PlaygroundRequest) => { setBusy(true); setError(null); try { const requestPayload = { conversation_id: conversationId, customer_id: request.customerId, message: "[redacted from operator projection]", execution_mode: request.executionMode }; const response = await api.chat(conversationId, request.customerId, request.message, request.executionMode); const nextRun = await api.run(response.agent_run_id); setRun(nextRun); setRecentRuns((current) => [nextRun, ...current.filter((item) => item.run_id !== nextRun.run_id)].slice(0, 25)); setPlaygroundExecution({ request, requestPayload, response, run: nextRun }); setPlaygroundRuns((current) => [{ run: nextRun, scenario: request.scenario, orderId: request.orderId }, ...current.filter((item) => item.run.run_id !== nextRun.run_id)].slice(0, 25)); setMemory(await api.memory(request.customerId)); const nextHealth = await api.health(); setHealth(nextHealth); setApiReachability("reachable"); } catch (caught) { if (caught instanceof ApiError && caught.status === 401) { setAuth(getApiAuthSnapshot()); setPlaygroundExecution(null); setMemory([]); setHealth(null); setApiReachability("unknown"); } else if (caught instanceof TypeError) { setHealth(null); setApiReachability("unavailable"); } setError(caught instanceof Error ? caught.message : "The operator API is unavailable."); } finally { setBusy(false); } };
  const selectRun = async (selected: AgentRun) => { setError(null); setRun(selected); setCustomerId(selected.customer_id); try { setRun(await api.run(selected.run_id)); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load the selected run."); } };
  const startNewWorkspaceChat = () => {
    if (busy) return;
    conversationLoad.current += 1;
    setConversationId(newConversationId("operator"));
    setTurns([]);
    setRun(null);
    setError(null);
  };
  const selectWorkspaceConversation = (id: string) => {
    if (busy) return;
    const record = getConversation(WORKSPACE_CONVERSATIONS_KEY, id);
    if (!record) return;
    const generation = ++conversationLoad.current;
    setConversationId(record.conversationId);
    setCustomerId(record.customerId);
    setTurns(record.turns);
    setError(null);
    setRun(null);
    if (!record.lastRunId) return;
    void api.run(record.lastRunId).then((nextRun) => {
      if (conversationLoad.current === generation) setRun(nextRun);
    }).catch(() => {
      if (conversationLoad.current === generation) setRun(null);
    });
  };
  const removeWorkspaceConversation = (id: string) => {
    if (busy) return;
    removeConversation(WORKSPACE_CONVERSATIONS_KEY, id);
    setWorkspaceConversations(loadConversations(WORKSPACE_CONVERSATIONS_KEY));
    if (id === conversationId) startNewWorkspaceChat();
  };
  const openRunDetail = (runId: string) => { window.history.pushState({}, "", `/runs/${encodeURIComponent(runId)}`); setLocationPath(window.location.pathname); };
  const closeRunDetail = () => { window.history.pushState({}, "", "/"); setLocationPath("/"); };
  const navigateToView = (nextView: ConsoleView) => { const nextPath = nextView === "overview" ? "/overview" : nextView === "chat" ? "/chat" : nextView === "architecture" ? "/architecture" : nextView === "showcase" ? "/showcase" : "/"; window.history.pushState({}, "", nextPath); setLocationPath(nextPath); setView(nextView); };
  const runSafetyDemo = async () => { navigateToView("playground"); await runPlayground({ message: "I received a damaged product and want a refund", customerId: 1, orderId: "", scenario: "valid-refund", executionMode: "recorded_replay" }); };
  const clearPlayground = () => { setPlaygroundExecution(null); setError(null); };
  const lastUpdated = useMemo(() => run ? new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—", [run]);
  if (auth.status !== "authenticated") return <AuthBoundary snapshot={auth} />;
  return <div className="min-h-screen"><header className="topbar"><div className="topbar-inner flex-wrap"><div className="flex items-center gap-3"><div className="brand-mark brand-mark-small"><Bot size={15} aria-hidden="true" /></div><span className="text-sm font-semibold tracking-[.12em] text-main">AGENTIC OPS</span><span className="hidden text-xs text-muted sm:inline">/ control plane</span></div><nav className="console-nav" aria-label="Console views"><button type="button" title="What the system guarantees" className={`console-nav-button ${view === "overview" ? "console-nav-active" : ""}`} onClick={() => navigateToView("overview")}><Compass size={14} aria-hidden="true" />Overview</button><button type="button" title="Customer interaction with agent observability" className={`console-nav-button ${view === "chat" ? "console-nav-active" : ""}`} onClick={() => navigateToView("chat")}><MessageSquareText size={14} aria-hidden="true" />Chat + activity</button><button type="button" title="Operate the current decision surface" className={`console-nav-button ${view === "workspace" ? "console-nav-active" : ""}`} onClick={() => navigateToView("workspace")}><LayoutDashboard size={14} aria-hidden="true" />Workspace</button><button type="button" title="Submit a controlled scenario" className={`console-nav-button ${view === "playground" ? "console-nav-active" : ""}`} onClick={() => navigateToView("playground")}><Beaker size={14} aria-hidden="true" />Playground</button><button type="button" title="Review recorded evidence" className={`console-nav-button ${view === "showcase" ? "console-nav-active" : ""}`} onClick={() => navigateToView("showcase")}><ShieldCheck size={14} aria-hidden="true" />Showcase</button><button type="button" title="How operators investigate failures" className={`console-nav-button ${view === "traces" ? "console-nav-active" : ""}`} onClick={() => navigateToView("traces")}><Activity size={14} aria-hidden="true" />Runs & traces</button><button type="button" title="How controls are validated" className={`console-nav-button ${view === "evidence" ? "console-nav-active" : ""}`} onClick={() => navigateToView("evidence")}><ShieldCheck size={14} aria-hidden="true" />Safety</button><button type="button" title="How authority boundaries are designed" className={`console-nav-button ${view === "architecture" ? "console-nav-active" : ""}`} onClick={() => navigateToView("architecture")}><Network size={14} aria-hidden="true" />Architecture</button></nav><div className="flex items-center gap-4"><span className="hidden text-xs text-muted xl:inline">source-bound operator view</span><StatusIndicator label="Authenticated" tone="success" compact /></div></div></header><main className="mx-auto max-w-[1760px] space-y-5 px-4 py-5 sm:px-6 lg:px-8">{routeRunId ? <RunInvestigationPage run={run} memoryRecords={memory} availableRuns={run ? [run, ...recentRuns.filter((item) => item.run_id !== run.run_id)] : recentRuns} loading={routeRunLoading} error={routeRunError} onBack={closeRunDetail} /> : view === "overview" ? <OverviewDashboard runs={recentRuns} busy={busy} onRunSafetyDemo={runSafetyDemo} onNavigate={(nextView) => navigateToView(nextView)} /> : view === "chat" ? <ChatWindow /> : view === "architecture" ? <ArchitectureOverview /> : view === "showcase" ? <DemoShowcase scenarios={demoScenarios} /> : view === "workspace" ? <><RunHeader run={run} conversationId={conversationId} /><div className="workspace-control-grid"><WorkspaceRail runs={recentRuns} selectedRunId={run?.run_id ?? null} activeConversationId={conversationId} conversations={workspaceConversations} busy={busy} onSelect={selectRun} onNewChat={startNewWorkspaceChat} onSelectConversation={selectWorkspaceConversation} onRemoveConversation={removeWorkspaceConversation} /><Playground customerId={customerId} conversationId={conversationId} turns={turns} busy={busy} error={error} onCustomerChange={setCustomerId} onSend={send} onNewChat={startNewWorkspaceChat} /><Inspector run={run} memoryRecords={memory} /></div><div className="grid gap-5 xl:grid-cols-[1.15fr_1fr_1fr]"><TraceTimeline events={run?.trace ?? []} run={run} /><ResiliencePanel health={health} run={run} /><section className="surface p-5"><div className="eyebrow">Run context</div><h2 className="section-title mt-1">Correlation</h2><div className="mt-4 divide-y divide-border/70"><DataRow label="Last activity" value={lastUpdated} /><DataRow label="Conversation" value={conversationId} mono /><DataRow label="Scope" value={`customer #${customerId}`} /></div></section></div><SystemHealthStrip health={health} apiReachability={apiReachability} /></> : view === "playground" ? <AgentPlayground runtimeConfig={runtimeConfig} busy={busy} error={error} execution={playgroundExecution} demoScenarios={demoScenarios} onRun={runPlayground} onClear={clearPlayground} onOpenLatestTrace={() => { if (playgroundExecution) openRunDetail(playgroundExecution.run.run_id); }} /> : view === "traces" ? <TraceDashboard runs={recentRuns} playgroundRuns={playgroundRuns} onSelect={(selected) => openRunDetail(selected.run_id)} /> : <SafetyDashboard onOpenRuns={() => navigateToView("traces")} />}</main><footer className="mx-auto max-w-[1760px] px-4 pb-8 text-[11px] text-muted sm:px-6 lg:px-8">Operator surface for debugging and demonstrations · prompts, raw payloads, and chain-of-thought are not displayed.</footer></div>;
}
