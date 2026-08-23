import { BookOpen, CheckCircle2, FileText } from "lucide-react";
import type { RagDocument } from "../types";
import { Badge, EmptyState, Panel, SectionHeader } from "./ui";

export function RagPanel({ documents, retrievalRecorded = false, embedded = false }: { documents: RagDocument[]; retrievalRecorded?: boolean; embedded?: boolean }) {
  const emptyState = retrievalRecorded
    ? <EmptyState title="Evidence unavailable from current projection" description="A retrieval stage was recorded, but no document metadata is available to this operator view." icon={BookOpen} />
    : <EmptyState title="No retrieval stage recorded" description="This run contains no recorded RAG retrieval stage." icon={BookOpen} />;
  const content = <>
    <div className="context-role-header">
      <div className="flex flex-wrap items-center gap-2">
        <div className="eyebrow">RAG evidence</div>
        <Badge tone="success">KNOWLEDGE RETRIEVAL</Badge>
      </div>
      <p className="mt-1 text-xs leading-5 text-muted">External knowledge retrieval and evidence grounding.</p>
    </div>
    {documents.length === 0 ? emptyState : <div className="mt-3 space-y-3"><div className="grounding-status"><CheckCircle2 size={15} className="text-success" aria-hidden="true" /><div><div className="text-xs font-medium text-main">Evidence retrieved</div><div className="mt-1 text-[11px] text-muted">Bounded document metadata supports grounding inspection; raw content is not exposed.</div></div></div><div className="space-y-2">{documents.map((doc) => <div className="source-row" key={doc.citation_id}><div className="source-icon"><FileText size={15} aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-main">{doc.title}</div><div className="mt-1 text-xs text-muted">Document section · {doc.section}</div><div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-info"><span>Citation [{doc.citation_id}]</span><span className="text-muted">Source {doc.source}</span></div></div><div className="shrink-0 text-right"><div className="field-label">Score</div><Badge tone="info">{doc.score.toFixed(2)}</Badge></div></div>)}</div></div>}
  </>;
  return embedded ? <div>{content}</div> : <Panel title="Knowledge retrieval" eyebrow="Grounded evidence"><SectionHeader title="Retrieved sources" description="Document metadata only; raw knowledge content stays private." />{content}</Panel>;
}
