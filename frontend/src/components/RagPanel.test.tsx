import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RagPanel } from "./RagPanel";

describe("RagPanel", () => {
  it("distinguishes an unrecorded retrieval stage from unavailable evidence", () => {
    const notRecorded = renderToStaticMarkup(<RagPanel documents={[]} embedded />);
    const unavailable = renderToStaticMarkup(<RagPanel documents={[]} retrievalRecorded embedded />);

    expect(notRecorded).toContain("No retrieval stage recorded");
    expect(unavailable).toContain("Evidence unavailable from current projection");
    expect(notRecorded).toContain("KNOWLEDGE RETRIEVAL");
  });

  it("labels returned document metadata as retrieved evidence", () => {
    const html = renderToStaticMarkup(<RagPanel documents={[{ citation_id: "ref-1", title: "Refund policy", section: "Eligibility", source: "policy", score: 0.91 }]} embedded />);

    expect(html).toContain("Evidence retrieved");
    expect(html).toContain("KNOWLEDGE RETRIEVAL");
    expect(html).toContain("Refund policy");
  });
});
