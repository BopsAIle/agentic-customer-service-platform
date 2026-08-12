import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SystemHealthStrip } from "./SystemHealth";

describe("system health projection", () => {
  it("distinguishes an unreachable API from backend runtime readiness", () => {
    const html = renderToStaticMarkup(
      <SystemHealthStrip health={null} apiReachability="unavailable" />,
    );
    expect(html).toContain("API unreachable");
    expect(html).not.toContain("API connected");
  });

  it("renders mixed component health without a false-green aggregate", () => {
    const html = renderToStaticMarkup(
      <SystemHealthStrip
        apiReachability="reachable"
        health={{
          status: "not_ready",
          components: [
            { name: "database", status: "healthy", detail: "PostgreSQL reachable" },
            { name: "retriever", status: "unavailable", detail: "Qdrant unavailable" },
            {
              name: "llm",
              status: "not_probed",
              detail: "LLM provider configured; availability not actively probed",
            },
          ],
        }}
      />,
    );
    expect(html).toContain("not ready");
    expect(html).toContain("retriever · unavailable");
    expect(html).toContain("llm · not_probed");
    expect(html).not.toContain(">healthy<");
  });

  it("renders a ready backend only after a successful health response", () => {
    const html = renderToStaticMarkup(
      <SystemHealthStrip
        apiReachability="reachable"
        health={{ status: "ready", components: [] }}
      />,
    );
    expect(html).toContain(">ready<");
  });
});
