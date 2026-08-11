type Props = { title: string; eyebrow?: string; children: React.ReactNode; className?: string };

export function Panel({ title, eyebrow, children, className = "" }: Props) {
  return (
    <section className={`rounded-2xl border border-line bg-panel/80 p-5 shadow-glow ${className}`}>
      {eyebrow && <div className="mb-2 text-[10px] font-bold uppercase tracking-[.22em] text-mint/70">{eyebrow}</div>}
      <h2 className="mb-4 text-sm font-semibold tracking-wide text-white">{title}</h2>
      {children}
    </section>
  );
}
