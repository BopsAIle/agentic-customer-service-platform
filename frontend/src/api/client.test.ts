import { afterEach, describe, expect, it, vi } from "vitest";

import { createAuthProvider, ExternalSessionProvider } from "../auth/provider";
import { ApiError, api, initializeApiAuth, setApiAuthProvider } from "./client";

afterEach(() => {
  setApiAuthProvider(createAuthProvider("local_demo", null));
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("authenticated API client", () => {
  it("attaches the configured bearer credential", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ready", components: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setApiAuthProvider(createAuthProvider("local_demo", "session-demo-token"));
    await initializeApiAuth();

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
    const provider = createAuthProvider("local_demo", token);
    setApiAuthProvider(provider);
    await initializeApiAuth();

    const failure = await api.health().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect((failure as Error).message).toContain("Authentication session is missing or expired");
    expect((failure as Error).message).not.toContain(token);
    expect(provider.getSnapshot().status).toBe("unauthenticated");
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("does not call protected APIs when production authentication is missing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setApiAuthProvider(new ExternalSessionProvider(null));
    await initializeApiAuth();

    const failure = await api.health().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(0);
    expect((failure as Error).message).toContain("Production authentication is not configured");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves authenticated state for 403 responses", async () => {
    const provider = createAuthProvider("integration", "integration-test-token");
    setApiAuthProvider(provider);
    await initializeApiAuth();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })));

    const failure = await api.health().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(403);
    expect(provider.getSnapshot().status).toBe("authenticated");
  });

  it("forwards an external session credential without persisting or rendering it", async () => {
    const secret = "external-session-secret";
    setApiAuthProvider(
      new ExternalSessionProvider({
        getSession: async () => ({ authenticated: true, accessCredential: secret }),
      }),
    );
    await initializeApiAuth();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ready", components: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.health();

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe(`Bearer ${secret}`);
    expect(request.credentials).toBe("include");
  });

  it("boundedly retries a transient agent-run projection 404", async () => {
    const projection = { run_id: "run-1", status: "completed" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(projection), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    setApiAuthProvider(createAuthProvider("local_demo", "session-demo-token"));
    await initializeApiAuth();

    await expect(api.run("run-1")).resolves.toEqual(projection);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
