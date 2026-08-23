import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentPlayground } from "./AgentPlayground";

describe("playground showcase scenarios", () => {
  it("exposes context and authority-boundary inputs without fabricating results", () => {
    const html = renderToStaticMarkup(<AgentPlayground busy={false} error={null} execution={null} onRun={async () => undefined} onClear={() => undefined} />);
    expect(html).toContain("Memory · saved preference");
    expect(html).toContain("RAG · refund policy");
    expect(html).toContain("Prompt injection attempt");
    expect(html).toContain("A covered mutation remains unexecuted until the confirmation boundary is satisfied.");
    expect(html).toContain("Selecting a scenario populates inputs only");
    expect(html).not.toContain("fake execution result");
  });
});
