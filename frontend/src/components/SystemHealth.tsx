import { HeartPulse } from "lucide-react";
import type { ComponentHealthStatus, Health } from "../types";
import { Badge, StatusIndicator } from "./ui";

export type ApiReachability = "unknown" | "reachable" | "unavailable";

export function healthComponentTone(status: ComponentHealthStatus) {
  if (status === "healthy") return "success" as const;
  if (status === "unavailable" || status === "incompatible") return "warning" as const;
  return "neutral" as const;
}

export function SystemHealthStrip({
  health,
  apiReachability,
}: {
  health: Health | null;
  apiReachability: ApiReachability;
}) {
  const overallLabel = health
    ? health.status === "ready"
      ? "ready"
      : "not ready"
    : apiReachability === "unavailable"
      ? "API unreachable"
      : apiReachability === "reachable"
        ? "health unavailable"
        : "waiting for backend health";
  const overallTone = health?.status === "ready" ? "success" : "warning";
  return (
    <section className="surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <HeartPulse size={15} className="text-success" aria-hidden="true" />
          <span className="text-sm font-medium text-main">System status</span>
          <Badge tone={overallTone}>{overallLabel}</Badge>
        </div>
        <div className="flex flex-wrap gap-4">
          {(health?.components ?? []).map((component) => (
            <StatusIndicator
              key={component.name}
              label={`${component.name} · ${component.status}`}
              tone={healthComponentTone(component.status)}
              compact
            />
          ))}
        </div>
      </div>
    </section>
  );
}
