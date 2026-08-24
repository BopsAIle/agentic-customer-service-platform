import { Activity, ArrowRight, Beaker, BookOpen, CheckCircle2, FileSearch, GitBranch, LockKeyhole, ShieldCheck, Waypoints } from "lucide-react";
import type { AgentRun } from "../types";
import { Badge, Card, MetricCard, SectionHeader, StatusIndicator } from "./ui";

type Props = {
  runs: AgentRun[];
  busy: boolean;
  onRunSafetyDemo: () => Promise<void>;
  onNavigate: (view: "playground" | "traces" | "evidence") => void;
};

const safetyEvidence = [
  { label: "Unsafe executions", value: "0", detail: "M6.29B D2c + M6.34 D2d" },
  { label: "Confirmation bypasses", value: "0", detail: "Release invariant" },
  { label: "Unauthorized mutations", value: "0", detail: "D2d operational gate" },
  { label: "Duplicate mutations", value: "0", detail: "D2d concurrency gate" },
];

function projectedCount(value: number): string {
  return value > 0 ? String(value) : "Not available";
}

function runCounts(runs: AgentRun[]) {
  return {
    total: runs.length,
    completed: runs.filter((run) => run.status === "completed").length,
    blocked: runs.filter((run) => run.status === "blocked" || run.status === "error").length,
    pending: runs.filter((run) => run.status === "waiting_confirmation").length,
  };
}

function contextCounts(runs: AgentRun[]) {
  return {
    memory: runs.filter((run) => run.memory.retrieved === true || (run.memory.items_used ?? run.memory.retrieved_count ?? run.memory.item_count) > 0).length,
    rag: runs.filter((run) => run.rag_documents.length > 0).length,
  };
}

function authorityCounts(runs: AgentRun[]) {
  return {
    mutations: runs.filter((run) => ["executed", "committed"].includes(run.evidence.write_outcome.status)).length,
    confirmations: runs.filter((run) => run.evidence.confirmation.required).length,
  };
}

export function OverviewDashboard({ runs, busy, onRunSafetyDemo, onNavigate }: Props) {
  const counts = runCounts(runs);
  const context = contextCounts(runs);
  const authority = authorityCounts(runs);
  return <div className="space-y-5">
    <section className="overview-hero surface">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="max-w-3xl">
          <div className="eyebrow">Control plane</div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-main">Agent Platform</h1>
          <p className="mt-3 text-sm leading-6 text-muted">Inspect current runs, validation state, and execution boundaries.</p>
        </div>
        <StatusIndicator label="Evidence consolidated" tone="success" />
      </div>
      <div className="mt-6 flex flex-wrap gap-2">
        <button type="button" className="button-primary" onClick={() => { void onRunSafetyDemo(); }} disabled={busy}><Beaker size={15} aria-hidden="true" />{busy ? "Running safety demo…" : "Run Safety Demo"}</button>
        <button type="button" className="operator-action" onClick={() => onNavigate("playground")}><ArrowRight size={14} aria-hidden="true" />Open playground</button>
      </div>
    </section>

    <Card as="section" className="overview-evidence-summary p-5"><SectionHeader eyebrow="Evidence first" title="Current validation state" description="Published evidence is visible before the guided workflow; no synthetic run telemetry is added." /><div className="overview-evidence-grid"><div><span className="field-label">D2c semantic validation</span><strong>540/540 · CLOSED</strong><small>Current release-candidate benchmark.</small></div><div><span className="field-label">D2d operational gate</span><strong>RELEASE_GATE_PASS</strong><small>Deployment, recovery, and authority checks.</small></div><div><span className="field-label">Unsafe executions</span><strong>0</strong><small>Deterministic containment evidence.</small></div></div></Card>

    <Card as="section" className="p-5"><SectionHeader eyebrow="Reference release" title="System guarantees" description="Evidence-scoped guarantees expressed as control boundaries, not marketing claims." /><div className="overview-guarantees-grid"><div><strong>LLM cannot execute</strong><small>Model outputs remain proposals. Runtime authority stays behind deterministic controls.</small></div><div><strong>Decisions require validation</strong><small>Provenance, policy, and target checks are evaluated before covered actions.</small></div><div><strong>Evidence-backed operation</strong><small>Context sources provide grounding but never receive execution authority.</small></div><div><strong>Duplicate effects are prevented</strong><small>Persistence-backed idempotency and concurrency controls protect mutations.</small></div></div></Card>

    <Card as="section" className="p-5"><SectionHeader eyebrow="Available actions" title="Move from a request to evidence" description="Use the existing projections to follow a scenario from input through validation." /><div className="guided-journey"><button type="button" className="journey-step" onClick={() => { void onRunSafetyDemo(); }} disabled={busy}><span className="journey-number">1</span><Beaker size={17} className="text-info" aria-hidden="true" /><span><strong>Try a scenario</strong><small>Run the damaged-product refund demo.</small></span><ArrowRight size={14} aria-hidden="true" /></button><button type="button" className="journey-step" onClick={() => onNavigate("traces")}><span className="journey-number">2</span><FileSearch size={17} className="text-info" aria-hidden="true" /><span><strong>Inspect the decision</strong><small>Open the observed trace and policy result.</small></span><ArrowRight size={14} aria-hidden="true" /></button><button type="button" className="journey-step" onClick={() => onNavigate("traces")}><span className="journey-number">3</span><GitBranch size={17} className="text-info" aria-hidden="true" /><span><strong>Review evidence</strong><small>Check grounding, retrieval, and bounded metadata.</small></span><ArrowRight size={14} aria-hidden="true" /></button><button type="button" className="journey-step" onClick={() => onNavigate("evidence")}><span className="journey-number">4</span><ShieldCheck size={17} className="text-success" aria-hidden="true" /><span><strong>Check validation</strong><small>Review D2c and D2d release evidence.</small></span><ArrowRight size={14} aria-hidden="true" /></button></div></Card>

    <section className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Loaded runs" title="Operational runs" description="Counts reflect the currently loaded run projection; no synthetic telemetry is added." />
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
          <MetricCard label="Projected runs" value={projectedCount(counts.total)} detail={counts.total ? "Loaded from operator API" : "Not available from current projection"} icon={Activity} />
          <MetricCard label="Successful" value={counts.total ? String(counts.completed) : "Not available"} detail="status = completed" icon={CheckCircle2} />
          <MetricCard label="Blocked / failed" value={counts.total ? String(counts.blocked) : "Not available"} detail="bounded status projection" icon={LockKeyhole} />
          <MetricCard label="Awaiting confirmation" value={counts.total ? String(counts.pending) : "Not available"} detail="confirmation_required" icon={ShieldCheck} />
        </div>
      </Card>
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Decision ownership" title="LLM proposes, deterministic systems decide" description="The model contributes a proposal. Authority remains behind validation, policy, confirmation, and execution controls." />
        <div className="overview-boundary-flow"><span className="overview-flow-proposal">LLM proposal</span><ArrowRight size={15} aria-hidden="true" /><span className="overview-flow-system">Validation + policy</span><ArrowRight size={15} aria-hidden="true" /><span className="overview-flow-authority">Execution authority</span></div>
        <div className="safety-explanation-grid"><div><span className="field-label">Proposal</span><strong>Untrusted model output</strong><small>Useful for semantic intent, never sufficient to mutate state.</small></div><div><span className="field-label">Decision</span><strong>Deterministic checks</strong><small>Provenance, target, policy, and confirmation boundaries.</small></div><div><span className="field-label">Authority</span><strong>System-owned execution</strong><small>Only approved runtime paths may commit business effects.</small></div></div>
      </Card>
    </section>

    <section className="grid gap-5 xl:grid-cols-2">
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Context integrity" title="Context sources" description="Counts reflect loaded run projections only; source content remains bounded." />
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
          <MetricCard label="Memory used" value={runs.length ? String(context.memory) : "Not available"} detail={runs.length ? "retrieved in loaded runs" : "Not available from current projection"} icon={Waypoints} />
          <MetricCard label="RAG evidence used" value={runs.length ? String(context.rag) : "Not available"} detail={runs.length ? "document metadata present" : "Not available from current projection"} icon={BookOpen} />
        </div>
      </Card>
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Authority boundary" title="Controlled effects" description="Mutation and confirmation states are projected from loaded runs, never synthesized." />
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
          <MetricCard label="Mutations executed" value={runs.length ? String(authority.mutations) : "Not available"} detail={runs.length ? "write outcome = executed/committed" : "Not available from current projection"} icon={LockKeyhole} />
          <MetricCard label="Confirmations required" value={runs.length ? String(authority.confirmations) : "Not available"} detail={runs.length ? "confirmation.required = true" : "Not available from current projection"} icon={ShieldCheck} />
        </div>
      </Card>
    </section>

    <section className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Safety evidence" title="Safety guarantees" description="Published release evidence only; this is not live production telemetry." />
        <div className="grid gap-3 sm:grid-cols-2">{safetyEvidence.map((item) => <div className="overview-safety-card" key={item.label}><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-main">{item.label}</span><StatusIndicator label="PASS" tone="success" compact /></div><div className="mt-3 font-mono text-2xl font-semibold text-success">{item.value}</div><div className="mt-1 text-[11px] text-muted">{item.detail}</div></div>)}</div>
      </Card>
      <Card as="section" className="p-5">
        <SectionHeader eyebrow="Release status" title="Evaluation status" description="Separate semantic validation from operational release evidence." />
        <div className="space-y-2"><div className="overview-status-row"><span>D2c semantic validation</span><Badge tone="success">540/540 · CLOSED</Badge></div><div className="overview-status-row"><span>D2d operational gate</span><Badge tone="success">RELEASE_GATE_PASS</Badge></div><div className="overview-status-row"><span>Reference release</span><Badge tone="info">Evidence consolidated</Badge></div></div>
        <button type="button" className="operator-action mt-4 w-full justify-center" onClick={() => onNavigate("evidence")}><GitBranch size={14} aria-hidden="true" />View safety evidence</button>
      </Card>
    </section>

    <Card as="section" className="p-5">
      <SectionHeader eyebrow="Next steps" title="What to inspect next" description="Follow the system from a submitted scenario to bounded operational evidence." />
      <div className="overview-next-grid"><button type="button" className="overview-next-card" onClick={() => onNavigate("playground")}><Beaker size={17} className="text-info" aria-hidden="true" /><span><strong>Submit a scenario</strong><small>Use the guided playground and safety library.</small></span><ArrowRight size={14} aria-hidden="true" /></button><button type="button" className="overview-next-card" onClick={() => onNavigate("traces")}><Activity size={17} className="text-info" aria-hidden="true" /><span><strong>Investigate a run</strong><small>Inspect trace stages, grounding, and policy.</small></span><ArrowRight size={14} aria-hidden="true" /></button><div className="overview-next-card overview-next-static"><ShieldCheck size={17} className="text-success" aria-hidden="true" /><span><strong>Execution stays bounded</strong><small>Confirmation and policy gates remain system-owned.</small></span></div></div>
    </Card>
  </div>;
}
