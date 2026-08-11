type Props = { children: React.ReactNode; tone?: "mint" | "amber" | "slate" | "red" };

const tones = {
  mint: "border-mint/25 bg-mint/10 text-mint",
  amber: "border-amber/25 bg-amber/10 text-amber",
  slate: "border-slate-500/25 bg-slate-500/10 text-slate-300",
  red: "border-red-400/25 bg-red-400/10 text-red-300",
};

export function Badge({ children, tone = "slate" }: Props) {
  return <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider ${tones[tone]}`}>{children}</span>;
}
