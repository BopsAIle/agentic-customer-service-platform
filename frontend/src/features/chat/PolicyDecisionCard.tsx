import { ShieldCheck } from "lucide-react";
import type { AgentRun } from "../../types";
import { Badge, Card } from "../../components/ui";

function decisionTone(outcome: string): "success" | "warning" | "danger" | "neutral" {
  if (outcome.includes("deny") || outcome.includes("reject")) return "danger";
  if (outcome.includes("confirm") || outcome.includes("pending")) return "warning";
  if (outcome.includes("allow") || outcome.includes("pass")) return "success";
  return "neutral";
}

function lastPolicyEvent(run: AgentRun) {
  return run.policy.length > 0 ? run.policy[run.policy.length - 1] : undefined;
}

export function PolicyDecisionCard({ run }: { run: AgentRun }) {
  const event = lastPolicyEvent(run);
  const outcome = event?.outcome ?? run.evidence.compiler.status ?? "not recorded";
  return (
    <Card className="p-4" data-testid="policy-decision-card" aria-label="Policy decision activity">
      <div className="flex items-center gap-2"><ShieldCheck size={15} className="text-warning" aria-hidden="true" /><span className="text-sm font-medium text-main">Policy decision</span><Badge tone={decisionTone(outcome)}>{outcome.replace(/_/g, " ")}</Badge></div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3"><div><span className="field-label">Compiler</span><div className="mt-1 text-xs text-main">{run.evidence.compiler.status.replace(/_/g, " ")}</div></div><div><span className="field-label">Confirmation</span><div className="mt-1 text-xs text-main">{run.evidence.confirmation.required ? "Required" : run.evidence.confirmation.status.replace(/_/g, " ")}</div></div><div><span className="field-label">Authority</span><div className="mt-1 text-xs text-main">{run.evidence.write_outcome.status.replace(/_/g, " ")}</div></div></div>
      {run.decision_reason && <p className="mt-3 border-l-2 border-warning/60 pl-3 text-xs leading-5 text-muted">{run.decision_reason}</p>}
      <p className="mt-3 text-[11px] leading-5 text-muted">This is a deterministic policy projection. Model output remains a proposal.</p>
    </Card>
  );
}
