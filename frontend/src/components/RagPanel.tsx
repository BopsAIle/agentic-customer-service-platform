import type { RagDocument } from "../types";
import { Badge } from "./Badge";
import { Empty } from "./Inspector";
import { Panel } from "./Panel";

export function RagPanel({ documents }: { documents: RagDocument[] }) { return <Panel title="Knowledge retrieval" eyebrow="Grounded evidence">{documents.length === 0 ? <Empty text="No retrieved knowledge documents in this run." /> : <div className="space-y-3">{documents.map((doc) => <div key={doc.citation_id} className="rounded-xl border border-line bg-ink/60 p-4"><div className="flex items-start justify-between gap-3"><div><div className="text-sm text-white">{doc.title}</div><div className="mt-1 text-xs text-slate-500">section · {doc.section}</div></div><Badge tone="mint">{doc.score.toFixed(2)}</Badge></div><div className="mt-3 font-mono text-[11px] text-mint/80">[{doc.citation_id}]</div><div className="mt-2 truncate text-xs text-slate-600">{doc.source}</div></div>)}</div>}</Panel>; }
