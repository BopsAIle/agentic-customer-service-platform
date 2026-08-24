import type { AgentResponse, AgentRun } from "../types";

export type RunSemanticStatus =
  | "waiting_confirmation"
  | "completed"
  | "blocked"
  | "failed_validation"
  | "needs_input"
  | "suspended"
  | "replaced"
  | "recorded";

export type RunSemantics = {
  decision: string;
  executionStatus: string;
  authority: string;
  status: RunSemanticStatus;
  clarification: boolean;
  waiting: boolean;
  denied: boolean;
  executed: boolean;
};

function lastPolicyOutcome(run: AgentRun): string | undefined {
  return run.policy.length > 0 ? run.policy[run.policy.length - 1]?.outcome : undefined;
}

function workflowStatus(run: AgentRun): "suspended" | "replaced" | undefined {
  const event = [...run.trace].reverse().find((item) => item.event_key?.startsWith("workflow."));
  const state = event?.metadata?.workflow_state;
  if (state === "suspended") return "suspended";
  if (state === "superseded") return "replaced";
  return undefined;
}

export function deriveRunSemantics(run: AgentRun): RunSemantics {
  const evidence = run.evidence ?? {};
  const policy = lastPolicyOutcome(run);
  const securityBlocked = run.security_signal === "instruction_override_attempt";
  const projectedDecision = evidence.decision && evidence.decision !== "not_recorded"
    ? evidence.decision
    : policy ?? evidence.compiler?.status ?? "not_recorded";
  const clarification = !securityBlocked && (projectedDecision === "clarification_required"
    || run.request_type === "unclear"
    || evidence.target_validation?.status === "missing_required_information");
  const workflow = workflowStatus(run);
  const waiting = !clarification && (projectedDecision === "require_confirmation"
    || run.status === "waiting_confirmation"
    || evidence.write_outcome?.status === "pending_confirmation");
  const executed = evidence.write_outcome?.status === "executed"
    || (run.tools ?? []).some((tool) => tool.status === "executed" || tool.status === "completed");
  const denied = projectedDecision === "deny" || evidence.write_outcome?.status === "blocked";
  const failedValidation = projectedDecision === "validation_failed"
    || projectedDecision === "compile_rejected";

  let status: RunSemanticStatus = "recorded";
  if (workflow) status = workflow;
  else if (clarification) status = "needs_input";
  else if (waiting) status = "waiting_confirmation";
  else if (executed) status = "completed";
  else if (failedValidation) status = "failed_validation";
  else if (denied) status = "blocked";
  else if (run.status === "error") status = "blocked";

  let executionStatus = evidence.execution_status || evidence.write_outcome?.status || "not_recorded";
  let authority = "not_granted";
  if (clarification) executionStatus = "not_attempted";
  else if (waiting) executionStatus = "blocked";
  else if (executed) executionStatus = "completed";
  else if (failedValidation) executionStatus = "failed_validation";
  else if (denied) executionStatus = "not_attempted";

  if (evidence.authority) authority = evidence.authority;
  else if (executed && evidence.write_outcome?.status === "not_applicable") authority = "read_access";
  else if (executed) authority = "controlled_execution";
  else if (waiting) authority = "confirmation_required";

  return {
    decision: projectedDecision,
    executionStatus,
    authority,
    status,
    clarification,
    waiting,
    denied,
    executed,
  };
}

export function responseState(response: AgentResponse): string {
  const pendingStatus = response.pending_action?.status;
  if (pendingStatus === "pending" || pendingStatus === "confirmed") return "awaiting confirmation";
  if (pendingStatus === "rejected" || pendingStatus === "expired" || pendingStatus === "failed") return "blocked";
  if (response.tool_call?.status === "executed" || response.tool_call?.status === "completed") return "completed";
  if (response.error_category === "invalid_tool_arguments") return "needs input";
  if (response.error_category === "policy_denied" || response.error_category === "duplicate_action") return "blocked";
  if (response.error_category) return "contained";
  return "decision recorded";
}
