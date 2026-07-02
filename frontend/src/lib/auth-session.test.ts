import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockAuthConfig = vi.hoisted(() => ({ value: { authMode: "keycloak" } }));

vi.mock("./config", () => ({
  getAuthConfig: () => mockAuthConfig.value,
}));

vi.mock("./auth-keycloak", () => ({
  keycloakSilentRefresh: vi.fn(),
  keycloakClearLocalSession: vi.fn().mockResolvedValue(undefined),
}));

// `auth-session.ts` reaches for `window` and `localStorage` directly and
// installs a `storage` listener at module load. We must therefore stub
// these globals *before* the import below is hoisted — `vi.hoisted`
// guarantees the callback runs before any static `import` statements.
const { localStorageStore, sessionStorageStore } = vi.hoisted(() => {
  const eventTarget = new EventTarget();
  const makeStorageStub = (store: Map<string, string>) => ({
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  });
  const localStore = new Map<string, string>();
  const sessionStore = new Map<string, string>();
  (globalThis as unknown as { localStorage: unknown }).localStorage = makeStorageStub(localStore);
  (globalThis as unknown as { sessionStorage: unknown }).sessionStorage = makeStorageStub(sessionStore);
  (globalThis as unknown as { window: unknown }).window = {
    addEventListener: eventTarget.addEventListener.bind(eventTarget),
    removeEventListener: eventTarget.removeEventListener.bind(eventTarget),
    dispatchEvent: eventTarget.dispatchEvent.bind(eventTarget),
  };
  // `CustomEvent` is only a global in Node 19+ and in browser/jsdom
  // environments; the CI/Docker test image runs an older Node, so we
  // polyfill the minimal surface area used by `auth-session.ts`.
  if (typeof (globalThis as { CustomEvent?: unknown }).CustomEvent === "undefined") {
    class CustomEventPolyfill<T> extends Event {
      detail: T;
      constructor(type: string, init?: { detail?: T }) {
        super(type);
        this.detail = init?.detail as T;
      }
    }
    (globalThis as unknown as { CustomEvent: unknown }).CustomEvent = CustomEventPolyfill;
  }
  return { localStorageStore: localStore, sessionStorageStore: sessionStore };
});

import {
  AUTH_EXPIRED_EVENT,
  __resetAuthSessionForTests,
  broadcastLogout,
  consumeCrossTabLogoutFlag,
  forceLogout,
  isAuthWhitelisted,
  markCrossTabLogout,
  onAuthExpired,
  tryRefreshSession,
} from "./auth-session";
import {
  keycloakClearLocalSession,
  keycloakSilentRefresh,
} from "./auth-keycloak";

const silentRefresh = vi.mocked(keycloakSilentRefresh);
const clearLocalSession = vi.mocked(keycloakClearLocalSession);

beforeEach(() => {
  __resetAuthSessionForTests();
  silentRefresh.mockReset();
  clearLocalSession.mockReset();
  clearLocalSession.mockResolvedValue(undefined);
  mockAuthConfig.value = { authMode: "keycloak" };
  localStorageStore.clear();
  sessionStorageStore.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("isAuthWhitelisted", () => {
  it("matches public auth endpoints", () => {
    expect(isAuthWhitelisted("/auth/config")).toBe(true);
    expect(isAuthWhitelisted("/auth/login")).toBe(true);
    expect(isAuthWhitelisted("/auth/register")).toBe(true);
  });

  it("ignores query strings", () => {
    expect(isAuthWhitelisted("/auth/login?next=/")).toBe(true);
  });

  it("does not match protected endpoints", () => {
    expect(isAuthWhitelisted("/auth/me")).toBe(false);
    expect(isAuthWhitelisted("/api/datasources")).toBe(false);
  });
});

describe("tryRefreshSession", () => {
  it("returns false in local-JWT mode without calling Keycloak", async () => {
    mockAuthConfig.value = { authMode: "local" };
    await expect(tryRefreshSession()).resolves.toBe(false);
    expect(silentRefresh).not.toHaveBeenCalled();
  });

  it("returns true when Keycloak silent refresh succeeds", async () => {
    silentRefresh.mockResolvedValue({ expired: false } as never);
    await expect(tryRefreshSession()).resolves.toBe(true);
  });

  it("returns false when Keycloak silent refresh rejects", async () => {
    silentRefresh.mockRejectedValue(new Error("nope"));
    await expect(tryRefreshSession()).resolves.toBe(false);
  });

  it("collapses concurrent calls into a single refresh (single-flight)", async () => {
    let resolveRefresh: (value: unknown) => void = () => undefined;
    silentRefresh.mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }) as never,
    );

    const a = tryRefreshSession();
    const b = tryRefreshSession();
    const c = tryRefreshSession();

    resolveRefresh({ expired: false });
    const results = await Promise.all([a, b, c]);

    expect(results).toEqual([true, true, true]);
    expect(silentRefresh).toHaveBeenCalledTimes(1);
  });
});

describe("forceLogout", () => {
  it("clears the local JWT, drops the OIDC session, and emits auth:expired", () => {
    localStorage.setItem("access_token", "stale");
    const events: string[] = [];
    const unsubscribe = onAuthExpired(({ reason }) => events.push(reason));

    forceLogout("expired");

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(clearLocalSession).toHaveBeenCalledTimes(1);
    expect(events).toEqual(["expired"]);
    unsubscribe();
  });

  it("deduplicates concurrent logout bursts into a single event", () => {
    const events: string[] = [];
    const unsubscribe = onAuthExpired(({ reason }) => events.push(reason));

    forceLogout("expired");
    forceLogout("expired");
    forceLogout("invalid");

    expect(events).toEqual(["expired"]);
    unsubscribe();
  });

  it("does not touch the OIDC store in local-JWT mode", () => {
    mockAuthConfig.value = { authMode: "local" };
    forceLogout("manual");
    expect(clearLocalSession).not.toHaveBeenCalled();
  });
});

describe("cross-tab broadcast", () => {
  function dispatchStorage(key: string | null, newValue: string | null): void {
    const event = new Event("storage") as Event & {
      key: string | null;
      newValue: string | null;
    };
    Object.assign(event, { key, newValue });
    window.dispatchEvent(event);
  }

  it("broadcastLogout writes a fresh timestamp under the shared key", () => {
    broadcastLogout();
    const written = localStorage.getItem("auth:logout:broadcast");
    expect(written).not.toBeNull();
    expect(Number(written)).toBeGreaterThan(0);
  });

  it("forceLogout writes the broadcast key for sibling tabs", () => {
    forceLogout("expired");
    expect(localStorage.getItem("auth:logout:broadcast")).not.toBeNull();
  });

  it("triggers cleanup with reason 'cross-tab' when a sibling tab writes the broadcast key", () => {
    localStorage.setItem("access_token", "stale");
    const events: string[] = [];
    const unsubscribe = onAuthExpired(({ reason }) => events.push(reason));

    dispatchStorage("auth:logout:broadcast", String(Date.now()));

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(clearLocalSession).toHaveBeenCalledTimes(1);
    expect(events).toEqual(["cross-tab"]);
    unsubscribe();
  });

  it("ignores storage events for unrelated keys", () => {
    const callback = vi.fn();
    const unsubscribe = onAuthExpired(callback);

    dispatchStorage("some-other-key", "value");

    expect(callback).not.toHaveBeenCalled();
    expect(clearLocalSession).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("ignores storage events with no newValue (key removal)", () => {
    const callback = vi.fn();
    const unsubscribe = onAuthExpired(callback);

    dispatchStorage("auth:logout:broadcast", null);

    expect(callback).not.toHaveBeenCalled();
    unsubscribe();
  });
});

describe("cross-tab logout flag", () => {
  it("markCrossTabLogout sets the sessionStorage flag", () => {
    markCrossTabLogout();
    expect(sessionStorage.getItem("auth:cross-tab-logout")).toBe("1");
  });

  it("consumeCrossTabLogoutFlag returns true once and clears the flag", () => {
    markCrossTabLogout();
    expect(consumeCrossTabLogoutFlag()).toBe(true);
    expect(consumeCrossTabLogoutFlag()).toBe(false);
    expect(sessionStorage.getItem("auth:cross-tab-logout")).toBeNull();
  });

  it("consumeCrossTabLogoutFlag returns false when no flag is set", () => {
    expect(consumeCrossTabLogoutFlag()).toBe(false);
  });
});

describe("onAuthExpired", () => {
  it("stops invoking the callback after unsubscribe", () => {
    const callback = vi.fn();
    const unsubscribe = onAuthExpired(callback);

    window.dispatchEvent(
      new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { reason: "expired" } }),
    );
    expect(callback).toHaveBeenCalledTimes(1);

    unsubscribe();
    window.dispatchEvent(
      new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { reason: "expired" } }),
    );
    expect(callback).toHaveBeenCalledTimes(1);
  });
});
