import { Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function EmptyState({ title, description, icon: Icon = Inbox }: { title: string; description: string; icon?: LucideIcon }) {
  return <div className="empty-state"><Icon size={18} strokeWidth={1.6} aria-hidden="true" /><div><div className="text-sm font-medium text-main">{title}</div><p className="mt-1 text-xs leading-5 text-muted">{description}</p></div></div>;
}
