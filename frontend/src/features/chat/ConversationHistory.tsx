import { Plus, Trash2 } from "lucide-react";

export type ConversationHistoryItem = {
  conversationId: string;
  customerId: number;
  updatedAt: string;
  title: string;
};

type Props = {
  items: ConversationHistoryItem[];
  activeId: string;
  busy: boolean;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  variant?: "panel" | "embedded";
};

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ConversationHistory({
  items,
  activeId,
  busy,
  onNewChat,
  onSelect,
  onRemove,
  variant = "panel",
}: Props) {
  const activeInList = items.some((item) => item.conversationId === activeId);
  const body = (
    <>
      <div className="p-3">
        <button type="button" className="button-primary w-full" data-testid="new-chat" disabled={busy} onClick={onNewChat}>
          <Plus size={15} aria-hidden="true" />
          New chat
        </button>
      </div>
      {!activeInList && (
        <div className="mx-2 mb-2 rounded-lg border border-info/30 bg-info/5 p-3" aria-current="true">
          <div className="text-xs font-semibold text-main">New chat</div>
          <div className="mt-1 truncate font-mono text-[10px] text-muted">{activeId}</div>
        </div>
      )}
      <div className="conversation-history-list">
        {items.length === 0 ? (
          <p className="px-2 py-3 text-xs leading-5 text-muted">No previous chats on this browser.</p>
        ) : items.map((item) => {
          const active = item.conversationId === activeId;
          return (
            <div
              key={item.conversationId}
              className={`rail-item flex items-start gap-1 ${active ? "rail-item-selected" : ""}`}
              data-testid="conversation-item"
              data-conversation-id={item.conversationId}
            >
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                disabled={busy}
                onClick={() => onSelect(item.conversationId)}
                aria-current={active ? "true" : undefined}
              >
                <div className="truncate text-xs font-semibold text-main">{item.title}</div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-muted">
                  <span>Customer #{item.customerId}</span>
                  <span>{formatUpdatedAt(item.updatedAt)}</span>
                </div>
              </button>
              <button
                type="button"
                className="rail-remove"
                data-testid="remove-conversation"
                aria-label={`Remove ${item.title}`}
                disabled={busy}
                onClick={() => onRemove(item.conversationId)}
              >
                <Trash2 size={12} aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </>
  );

  if (variant === "embedded") {
    return <div data-testid="conversation-history">{body}</div>;
  }

  return (
    <aside className="workspace-rail surface" data-testid="conversation-history" aria-label="Conversation history">
      <div className="border-b border-border p-4">
        <div className="eyebrow">Saved on this browser</div>
        <h2 className="section-title mt-1">Chats</h2>
      </div>
      {body}
    </aside>
  );
}
