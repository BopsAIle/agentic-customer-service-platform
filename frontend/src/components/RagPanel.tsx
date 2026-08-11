import { BookOpen, FileText } from "lucide-react";
import type { RagDocument } from "../types";
import { Badge, EmptyState, Panel, SectionHeader } from "./ui";

export function RagPanel({ documents, embedded = false }: { documents: RagDocument[]; embedded?: boolean }) {
  const content = documents.length === 0 ? <EmptyState title="No retrieval evidence" description="Knowledge sources will appear when RAG is used." icon={BookOpen} /> : <div className="space-y-2">{documents.map((doc) => <div className="source-row" key={doc.citation_id}><div className="source-icon"><FileText size={15} aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-main">{doc.title}</div><div className="mt-1 text-xs text-muted">Section · {doc.section}</div><div className="mt-2 font-mono text-[11px] text-info">[{doc.citation_id}]</div></div><Badge tone="info">{doc.score.toFixed(2)}</Badge></div>)}</div>;
  return embedded ? <div>{content}</div> : <Panel title="Knowledge retrieval" eyebrow="Grounded evidence"><SectionHeader title="Retrieved sources" description="Document metadata only; raw knowledge content stays private." />{content}</Panel>;
}
