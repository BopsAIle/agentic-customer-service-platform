import { Clock3, MessageSquare, ShieldAlert, UserRound } from "lucide-react";
import type { AgentRun } from "../types";
import { ConversationHistory, type ConversationHistoryItem } from "../features/chat/ConversationHistory";
import { Badge, EmptyState, StatusIndicator } from "./ui";

type Props = {
  runs: AgentRun[];
  selectedRunId: string | null;
  activeConversationId: string;
  conversations: ConversationHistoryItem[];
  busy: boolean;
  onSelect: (run: AgentRun) => void;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onRemoveConversation: (id: string) => void;
};

function runStatus(status: string): { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" } {
  if (status === "waiting_confirmation") return { label: "Awaiting confirmation", tone: "warning" };
  if (status === "completed") return { label: "Completed", tone: "success" };
  if (status === "error") return { label: "Escalated", tone: "danger" };
  return { label: status.replace(/_/g, " "), tone: "info" };
}

export function WorkspaceRail({
  runs,
  selectedRunId,
  activeConversationId,
  conversations,
  busy,
  onSelect,
  onNewChat,
  onSelectConversation,
  onRemoveConversation,
}: Props) {
  return (
    <aside className="workspace-rail surface" aria-label="Conversation list">
      <div className="border-b border-border p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="eyebrow">Operator queue</div>
            <h2 className="section-title mt-1">Conversations</h2>
          </div>
          <Badge tone="neutral">{runs.length} recent</Badge>
        </div>
        <p className="mt-2 text-xs leading-5 text-muted">Local chats on this browser, then recent run projections.</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ConversationHistory
          variant="embedded"
          items={conversations}
          activeId={activeConversationId}
          busy={busy}
          onNewChat={onNewChat}
          onSelect={onSelectConversation}
          onRemove={onRemoveConversation}
        />
        <div className="border-t border-border px-4 py-3">
          <div className="eyebrow">Recent runs</div>
          <p className="mt-1 text-[11px] leading-5 text-muted">Selecting a run opens its inspector. It does not restore a transcript.</p>
        </div>
        <div className="space-y-2 p-2">
          {runs.length === 0 ? (
            <EmptyState title="No persisted runs" description="A completed request will appear here with its bounded operator metadata." icon={MessageSquare} />
          ) : runs.map((run) => {
            const status = runStatus(run.status);
            const selected = run.run_id === selectedRunId;
            return (
              <button
                type="button"
                key={run.run_id}
                className={`rail-item w-full text-left ${selected ? "rail-item-selected" : ""}`}
                onClick={() => onSelect(run)}
                aria-pressed={selected}
              >
                <div className="flex items-start gap-2.5">
                  <div className="rail-icon"><UserRound size={14} aria-hidden="true" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <span className="truncate text-xs font-semibold text-main">Customer #{run.customer_id}</span>
                      <span className="shrink-0 text-[10px] text-muted">{new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-muted">{run.conversation_id}</div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="truncate text-[11px] text-muted">{run.intent || "Intent not recorded"}</span>
                      <StatusIndicator label={status.label} tone={status.tone} compact />
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <div className="mt-auto border-t border-border p-4 text-[11px] leading-5 text-muted">
        <div className="flex items-center gap-2"><Clock3 size={13} aria-hidden="true" /> bounded operational metadata</div>
        <div className="mt-2 flex items-center gap-2"><ShieldAlert size={13} className="text-warning" aria-hidden="true" /> proposal ≠ authority</div>
      </div>
    </aside>
  );
}
