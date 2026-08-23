import { useId, useRef, useState } from "react";
import type { ReactNode, KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";

export type Tab = { id: string; label: string; icon?: LucideIcon; content: ReactNode };

export function Tabs({ tabs, initialTab = tabs[0]?.id }: { tabs: Tab[]; initialTab?: string }) {
  const [active, setActive] = useState(initialTab);
  const tablistId = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeTab = tabs.find((tab) => tab.id === active) ?? tabs[0];
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length : -1;
    if (next >= 0) { event.preventDefault(); setActive(tabs[next].id); refs.current[next]?.focus(); }
  };
  if (!activeTab) return null;
  return <div><div className="tablist" role="tablist" aria-label="Agent run inspector" id={tablistId}>{tabs.map((tab, index) => { const Icon = tab.icon; const selected = tab.id === activeTab.id; return <button data-testid={`inspector-tab-${tab.id}`} key={tab.id} ref={(el) => { refs.current[index] = el; }} className={`tab ${selected ? "tab-active" : ""}`} role="tab" type="button" aria-selected={selected} aria-controls={`${tablistId}-${tab.id}`} tabIndex={selected ? 0 : -1} onClick={() => setActive(tab.id)} onKeyDown={(event) => onKeyDown(event, index)}>{Icon && <Icon size={14} strokeWidth={1.8} aria-hidden="true" />}{tab.label}</button>; })}</div><div id={`${tablistId}-${activeTab.id}`} role="tabpanel" tabIndex={0} className="pt-5">{activeTab.content}</div></div>;
}
