import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ArchitectureOverview } from "./ArchitectureOverview";
import { OverviewDashboard } from "./OverviewDashboard";

describe("platform presentation surfaces", () => {
  it("keeps overview metrics bounded when no run projection is available", () => {
    const html = renderToStaticMarkup(<OverviewDashboard runs={[]} busy={false} onRunSafetyDemo={async () => undefined} onNavigate={() => undefined} />);
    expect(html).toContain("Agent Platform");
    expect(html).toContain("Move from a request to evidence");
    expect(html).toContain("LLM proposes, deterministic systems decide");
    expect(html).toContain("Not available");
    expect(html).toContain("RELEASE_GATE_PASS");
    expect(html).toContain("Current validation state");
    expect(html).toContain("System guarantees");
    expect(html).toContain("Context integrity");
    expect(html).toContain("Authority boundary");
    expect(html).not.toContain("fake");
  });

  it("renders the documented execution authority boundary", () => {
    const html = renderToStaticMarkup(<ArchitectureOverview />);
    expect(html).toContain("LLM is not the execution authority");
    expect(html).toContain("Provenance validation");
    expect(html).toContain("Policy and confirmation");
    expect(html).toContain("context enrichment");
    expect(html).toContain("Memory");
    expect(html).toContain("RAG evidence");
    expect(html).toContain("Evidence inputs");
    expect(html).toContain("Supporting information. Never execution authority.");
    expect(html).toContain("Decision");
    expect(html).toContain("Authority");
    expect(html).toContain("Why LLM is not the execution authority");
    expect(html).toContain("Valid refund request");
  });
});
