export type AuthMode = "local_demo" | "integration" | "external_session";
export type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "misconfigured";

export type AuthSnapshot = {
  mode: AuthMode;
  status: AuthStatus;
};

export type ExternalSession = {
  authenticated: boolean;
  accessCredential?: string;
};

export type ExternalSessionAdapter = {
  getSession: () => Promise<ExternalSession>;
  clearSession?: () => Promise<void> | void;
};

export interface AuthProvider {
  readonly mode: AuthMode;
  initialize(): Promise<AuthSnapshot>;
  getAccessCredential(): string | null;
  getSnapshot(): AuthSnapshot;
  clearCredential(): void;
  usesCookieSession(): boolean;
}

class ConfiguredCredentialProvider implements AuthProvider {
  private snapshot: AuthSnapshot;

  constructor(
    readonly mode: "local_demo" | "integration",
    private readonly credential: string | null,
  ) {
    this.snapshot = {
      mode,
      status: "loading",
    };
  }

  async initialize(): Promise<AuthSnapshot> {
    this.snapshot = {
      mode: this.mode,
      status: this.credential ? "authenticated" : "misconfigured",
    };
    return this.snapshot;
  }

  getAccessCredential(): string | null {
    return this.snapshot.status === "authenticated" ? this.credential : null;
  }

  getSnapshot(): AuthSnapshot {
    return this.snapshot;
  }

  clearCredential(): void {
    this.snapshot = {
      mode: this.mode,
      status: "unauthenticated",
    };
  }

  usesCookieSession(): boolean {
    return false;
  }
}

export class ExternalSessionProvider implements AuthProvider {
  readonly mode = "external_session" as const;
  private snapshot: AuthSnapshot = {
    mode: "external_session",
    status: "loading",
  };
  private accessCredential: string | null = null;

  constructor(private readonly adapter: ExternalSessionAdapter | null) {}

  async initialize(): Promise<AuthSnapshot> {
    if (!this.adapter) {
      this.snapshot = { mode: this.mode, status: "misconfigured" };
      return this.snapshot;
    }
    try {
      const session = await this.adapter.getSession();
      this.accessCredential = session.accessCredential?.trim() || null;
      this.snapshot = {
        mode: this.mode,
        status: session.authenticated ? "authenticated" : "unauthenticated",
      };
      return this.snapshot;
    } catch {
      this.accessCredential = null;
      this.snapshot = { mode: this.mode, status: "unauthenticated" };
      return this.snapshot;
    }
  }

  getAccessCredential(): string | null {
    return this.snapshot.status === "authenticated" ? this.accessCredential : null;
  }

  getSnapshot(): AuthSnapshot {
    return this.snapshot;
  }

  clearCredential(): void {
    void this.adapter?.clearSession?.();
    this.accessCredential = null;
    this.snapshot = { mode: this.mode, status: "unauthenticated" };
  }

  usesCookieSession(): boolean {
    return true;
  }
}

function browserExternalSessionAdapter(): ExternalSessionAdapter | null {
  if (typeof window === "undefined") return null;
  return window.__OPERATOR_AUTH__ ?? null;
}

export function createAuthProvider(
  mode: AuthMode,
  credential: string | null = null,
  externalAdapter: ExternalSessionAdapter | null = browserExternalSessionAdapter(),
): AuthProvider {
  if (mode === "external_session") return new ExternalSessionProvider(externalAdapter);
  return new ConfiguredCredentialProvider(mode, credential?.trim() || null);
}

export function createConfiguredAuthProvider(): AuthProvider {
  const mode = import.meta.env.VITE_AUTH_MODE ?? "external_session";
  const credential = import.meta.env.VITE_DEMO_AUTH_TOKEN ?? null;
  if (mode === "local_demo" || mode === "integration" || mode === "external_session") {
    return createAuthProvider(mode, credential);
  }
  return new ExternalSessionProvider(null);
}

declare global {
  interface Window {
    /** Supplied by a trusted external session/BFF integration, never by bundled secrets. */
    __OPERATOR_AUTH__?: ExternalSessionAdapter;
  }
}
