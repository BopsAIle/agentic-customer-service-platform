import { Brain } from "lucide-react";
import type { MemoryRecord, MemoryUsage } from "../types";
import { EmptyState, Panel, SectionHeader, StatusIndicator } from "./ui";

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toISOString() : "no expiration";
}

export function MemoryPanel({
  usage,
  records,
  embedded = false,
}: {
  usage: MemoryUsage;
  records: MemoryRecord[];
  embedded?: boolean;
}) {
  const content = (
    <>
      <div className="notice notice-info">
        <Brain size={15} aria-hidden="true" />
        <span>
          Memory content is intentionally hidden from the operator projection. Memory does not
          authorize actions or satisfy confirmation.
        </span>
      </div>
      <div className="mt-4">
        <div className="eyebrow">Active memory · {usage.item_count} used in run</div>
        {records.length === 0 ? (
          <EmptyState
            title="No persistent memory found"
            description="This customer has no visible active memory records."
            icon={Brain}
          />
        ) : (
          <div className="mt-3 space-y-2">
            {records.map((record) => (
              <div className="memory-row" key={record.id}>
                <div>
                  <div className="text-sm font-medium text-main">
                    {record.memory_type.replace(/_/g, " ")}
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-muted">
                    {record.normalized_key}
                  </div>
                  <div className="mt-1 text-[11px] text-muted">
                    {record.source.replace(/_/g, " ")}
                  </div>
                  <div className="mt-1 text-[11px] text-muted">
                    Created {formatTimestamp(record.created_at)} · updated{" "}
                    {formatTimestamp(record.updated_at)} · expires {formatTimestamp(record.expires_at)}
                  </div>
                </div>
                <StatusIndicator label={record.status} tone="success" compact />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
  return embedded ? (
    <div>{content}</div>
  ) : (
    <Panel title="Customer memory" eyebrow="Contextual evidence">
      <SectionHeader
        title="Personalization context"
        description="Customer-scoped metadata approved by the memory policy."
      />
      {content}
    </Panel>
  );
}
