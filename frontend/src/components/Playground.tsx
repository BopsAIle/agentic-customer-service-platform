import { useState } from "react";
import type { ConversationTurn } from "../types";
import { Badge } from "./Badge";
import { Panel } from "./Panel";

type Props = {
  customerId: number;
  conversationId: string;
  turns: ConversationTurn[];
  busy: boolean;
  error: string | null;
  onCustomerChange: (id: number) => void;
  onSend: (message: string) => Promise<void>;
};

export function Playground({ customerId, conversationId, turns, busy, error, onCustomerChange, onSend }: Props) {
  const [message, setMessage] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!message.trim() || busy) return;
    const value = message;
    setMessage("");
    await onSend(value);
  };
  return (
    <Panel title="Agent playground" eyebrow="Simulation">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <label className="text-xs text-slate-400" htmlFor="customer">Customer</label>
        <select id="customer" value={customerId} onChange={(e) => onCustomerChange(Number(e.target.value))} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm text-white outline-none focus:border-mint/60">
          <option value={1}>customer_001 · Ada</option>
          <option value={2}>customer_002 · Grace</option>
          <option value={3}>customer_003 · Alan</option>
        </select>
        <Badge tone="slate">{conversationId.slice(0, 18)}</Badge>
      </div>
      <div className="mb-5 min-h-[300px] space-y-4 rounded-xl border border-line/80 bg-ink/60 p-4">
        {turns.length === 0 && <div className="flex h-64 items-center justify-center text-sm text-slate-500">Send a request to inspect the agent path.</div>}
        {turns.map(({ request, response: item }, index) => (
          <div key={`${item.agent_run_id}-${index}`} className="space-y-2">
            <div className="ml-auto max-w-[84%] rounded-2xl rounded-br-sm bg-slate-800 px-4 py-3 text-sm text-slate-200">{request}</div>
            <div className="max-w-[92%] rounded-2xl rounded-bl-sm border border-mint/15 bg-mint/5 px-4 py-3 text-sm leading-6 text-slate-200">
              {item.message}
              <div className="mt-3 flex flex-wrap gap-2"><Badge tone={item.failure_category ? "amber" : "mint"}>{item.intent}</Badge><Badge>{item.request_type}</Badge>{item.recovery_action && <Badge tone="amber">{item.recovery_action}</Badge>}</div>
            </div>
          </div>
        ))}
        {busy && <div className="text-xs text-mint">Agent is working through the graph…</div>}
      </div>
      {error && <div role="alert" className="mb-4 rounded-lg border border-red-400/25 bg-red-400/10 p-3 text-sm text-red-200">{error}</div>}
      <form onSubmit={submit} className="flex gap-3">
        <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask the agent about an order, policy, or memory…" className="min-w-0 flex-1 rounded-xl border border-line bg-ink px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-mint/60" />
        <button disabled={busy || !message.trim()} className="rounded-xl bg-mint px-5 py-3 text-sm font-bold text-ink transition hover:bg-mint/80 disabled:cursor-not-allowed disabled:opacity-40">Send</button>
      </form>
    </Panel>
  );
}
