import type { ReactNode } from "react";

export type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral" | "mint" | "amber" | "slate" | "red";
const tones: Record<BadgeTone, string> = {
  success: "badge-success", warning: "badge-warning", danger: "badge-danger", info: "badge-info", neutral: "badge-neutral",
  mint: "badge-success", amber: "badge-warning", slate: "badge-neutral", red: "badge-danger",
};

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`badge ${tones[tone]}`}>{children}</span>;
}
