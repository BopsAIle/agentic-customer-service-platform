import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentRun } from "../types";
import { TraceDashboard } from "./TraceDashboard";

const run = { run_id: "run-001", intent: "refund_order", request_type: "action", status: "completed", policy: [{ outcome: "allow" }], tools: [{ status: "executed" }], trace: [{ name: "respond" }] } as AgentRun;

describe("operational trace dashboard", () => {
  it("renders the bounded run index and trace availability", () => {
    const html = renderToStaticMarkup(<TraceDashboard runs={[run]} onSelect={() => undefined} />);
    expect(html).toContain("Runs &amp; traces");
    expect(html).toContain("refund_order");
    expect(html).toContain("Available");
    expect(html).not.toContain("SECRET_PAYLOAD");
  });

  it("renders explicit operator states", () => {
    expect(renderToStaticMarkup(<TraceDashboard runs={[]} loading onSelect={() => undefined} />)).toContain("Loading evidence snapshot...");
    expect(renderToStaticMarkup(<TraceDashboard runs={[]} error="backend unavailable" onSelect={() => undefined} />)).toContain("Investigation evidence unavailable");
    expect(renderToStaticMarkup(<TraceDashboard runs={[]} onSelect={() => undefined} />)).toContain("No recorded investigations available");
  });

  it("labels fixture-only filters and keeps the operator registry bounded", () => {
    const html = renderToStaticMarkup(<TraceDashboard runs={[run]} onSelect={() => undefined} />);
    expect(html).toContain("Filters apply to deterministic evidence snapshots.");
    expect(html).toContain("Evidence snapshot");
    expect(html).toContain("Scenario");
    expect(html).toContain("Status");
  });
});
