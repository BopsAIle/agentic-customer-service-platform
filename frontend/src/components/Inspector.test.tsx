import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Badge } from "./Badge";

describe("operator console components", () => {
  it("renders a bounded status badge", () => {
    const html = renderToStaticMarkup(<Badge tone="mint">Healthy</Badge>);
    expect(html).toContain("Healthy");
    expect(html).toContain("badge-success");
  });
});
