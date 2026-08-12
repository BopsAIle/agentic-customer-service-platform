import { describe, expect, it, vi } from "vitest";

import { createAuthProvider, ExternalSessionProvider } from "./provider";

describe("operator authentication providers", () => {
  it("authenticates with an explicit local demo credential in memory", async () => {
    const provider = createAuthProvider("local_demo", "local-demo-test-token");

    await expect(provider.initialize()).resolves.toEqual({
      mode: "local_demo",
      status: "authenticated",
    });
    expect(provider.getAccessCredential()).toBe("local-demo-test-token");
  });

  it("supports the explicit integration credential mode", async () => {
    const provider = createAuthProvider("integration", "integration-test-token");

    await provider.initialize();

    expect(provider.getSnapshot()).toEqual({ mode: "integration", status: "authenticated" });
    expect(provider.usesCookieSession()).toBe(false);
  });

  it("fails closed when production has no external session adapter", async () => {
    const provider = new ExternalSessionProvider(null);

    await expect(provider.initialize()).resolves.toEqual({
      mode: "external_session",
      status: "misconfigured",
    });
    expect(provider.getAccessCredential()).toBeNull();
  });

  it("accepts a test external session adapter without rendering the credential", async () => {
    const clearSession = vi.fn();
    const provider = new ExternalSessionProvider({
      getSession: async () => ({
        authenticated: true,
        accessCredential: "external-session-secret",
      }),
      clearSession,
    });

    await provider.initialize();

    expect(provider.getSnapshot().status).toBe("authenticated");
    expect(provider.getAccessCredential()).toBe("external-session-secret");
    provider.clearCredential();
    expect(clearSession).toHaveBeenCalledOnce();
    expect(provider.getSnapshot().status).toBe("unauthenticated");
  });
});
