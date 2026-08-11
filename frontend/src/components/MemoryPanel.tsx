import type { MemoryRecord, MemoryUsage } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function MemoryPanel({ usage, records }: { usage: MemoryUsage; records: MemoryRecord[] }) { return <Panel title="Customer memory" eyebrow="Contextual evidence"><div className="mb-4 flex gap-2"><Badge tone="mint">{usage.item_count} used in run</Badge>{usage.types.map((type) => <Badge key={type}>{type}</Badge>)}</div>{records.length === 0 ? <Empty text="No active memory for this customer." /> : <div className="space-y-3">{records.map((record) => <div key={record.id} className="rounded-xl border border-line bg-ink/60 p-4"><div className="flex items-center justify-between"><Badge tone="mint">{record.memory_type}</Badge><span className="text-[11px] text-slate-500">{record.expires_at ? `expires ${new Date(record.expires_at).toLocaleDateString()}` : "durable"}</span></div><div className="mt-3 text-sm text-slate-200">{record.content}</div><div className="mt-2 font-mono text-[11px] text-slate-600">{record.normalized_key}</div></div>)}</div>}</Panel>; }
