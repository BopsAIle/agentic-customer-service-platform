import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, setApiBearerToken } from "./client";

afterEach(() => {
  setApiBearerToken(null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("authenticated API client", () => {
  it("attaches the configured bearer credential", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "healthy", components: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setApiBearerToken("session-demo-token");

    await api.health();

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe(
      "Bearer session-demo-token",
    );
  });

  it("handles authorization failures without logging or exposing the credential", async () => {
    const token = "never-render-or-log-this-token";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    setApiBearerToken(token);

    const failure = await api.health().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect((failure as Error).message).toContain("Authentication failed");
    expect((failure as Error).message).not.toContain(token);
    expect(consoleSpy).not.toHaveBeenCalled();
  });
});
