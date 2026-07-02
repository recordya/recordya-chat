import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ConfigModule = typeof import("./config");

async function freshConfig(): Promise<ConfigModule> {
  vi.resetModules();
  return await import("./config");
}

describe("config", () => {
  beforeEach(() => {
    vi.stubGlobal("console", { ...console, warn: vi.fn() });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  describe("getApiUrl", () => {
    it("returns default URL before loadConfig is called", async () => {
      const { getApiUrl } = await freshConfig();
      expect(getApiUrl()).toBe("http://localhost:8000");
    });
  });

  describe("getShowBranding", () => {
    it("returns false by default before loadConfig is called", async () => {
      const { getShowBranding } = await freshConfig();
      expect(getShowBranding()).toBe(false);
    });

    it("returns true when config sets showBranding to true", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "http://localhost:8000", showBranding: true }),
        })
      );

      const { loadConfig, getShowBranding } = await freshConfig();
      await loadConfig();

      expect(getShowBranding()).toBe(true);
    });

    it("returns false when config omits showBranding", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "http://localhost:8000" }),
        })
      );

      const { loadConfig, getShowBranding } = await freshConfig();
      await loadConfig();

      expect(getShowBranding()).toBe(false);
    });
  });

  describe("loadConfig", () => {
    it("loads apiUrl from config.json on successful fetch", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "https://api.production.example.com" }),
        })
      );

      const { loadConfig, getApiUrl } = await freshConfig();
      await loadConfig();

      expect(getApiUrl()).toBe("https://api.production.example.com");
      expect(fetch).toHaveBeenCalledWith("/config/config.json");
    });

    it("keeps default URL when fetch returns non-ok response", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 404,
        })
      );

      const { loadConfig, getApiUrl } = await freshConfig();
      await loadConfig();

      expect(getApiUrl()).toBe("http://localhost:8000");
      expect(console.warn).toHaveBeenCalledWith(
        "Failed to load config.json, using defaults"
      );
    });

    it("keeps default URL when fetch throws a network error", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
      );

      const { loadConfig, getApiUrl } = await freshConfig();
      await loadConfig();

      expect(getApiUrl()).toBe("http://localhost:8000");
      expect(console.warn).toHaveBeenCalledWith(
        "Could not fetch config.json, using defaults"
      );
    });

    it("overwrites previously loaded config on subsequent call", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "https://first.example.com" }),
        })
      );

      const { loadConfig, getApiUrl } = await freshConfig();
      await loadConfig();
      expect(getApiUrl()).toBe("https://first.example.com");

      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "https://second.example.com" }),
        })
      );

      await loadConfig();
      expect(getApiUrl()).toBe("https://second.example.com");
    });

    it("loads showBranding from config.json", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ apiUrl: "http://localhost:8000", showBranding: true }),
        })
      );

      const { loadConfig, getShowBranding } = await freshConfig();
      await loadConfig();

      expect(getShowBranding()).toBe(true);
      expect(fetch).toHaveBeenCalledWith("/config/config.json");
    });

    it("defaults showBranding to false when fetch fails", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
      );

      const { loadConfig, getShowBranding } = await freshConfig();
      await loadConfig();

      expect(getShowBranding()).toBe(false);
    });

    it("defaults showBranding to false when response is not ok", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: false, status: 500 })
      );

      const { loadConfig, getShowBranding } = await freshConfig();
      await loadConfig();

      expect(getShowBranding()).toBe(false);
    });
  });

  describe("getAuthConfig", () => {
    it("returns local auth mode by default", async () => {
      const { getAuthConfig } = await freshConfig();
      expect(getAuthConfig().authMode).toBe("local");
    });

    it("returns keycloak config after loadConfig with backend response", async () => {
      let callCount = 0;
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          callCount++;
          if (url.includes("config.json")) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ apiUrl: "http://localhost:8000" }),
            });
          }
          // /auth/config
          return Promise.resolve({
            ok: true,
            json: async () => ({
              auth_mode: "keycloak",
              keycloak_url: "http://localhost:8180",
              keycloak_realm: "recordya",
              keycloak_client_id: "recordya-chat",
            }),
          });
        })
      );

      const { loadConfig, getAuthConfig } = await freshConfig();
      await loadConfig();

      const auth = getAuthConfig();
      expect(auth.authMode).toBe("keycloak");
      expect(auth.keycloakUrl).toBe("http://localhost:8180");
      expect(auth.keycloakRealm).toBe("recordya");
      expect(auth.keycloakClientId).toBe("recordya-chat");
    });

    it("keeps local mode when backend /auth/config fails", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          if (url.includes("config.json")) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ apiUrl: "http://localhost:8000" }),
            });
          }
          return Promise.resolve({ ok: false, status: 500 });
        })
      );

      const { loadConfig, getAuthConfig } = await freshConfig();
      await loadConfig();

      expect(getAuthConfig().authMode).toBe("local");
    });
  });

  describe("getLocale", () => {
    it("returns English locale by default", async () => {
      const { getLocale } = await freshConfig();
      expect(getLocale()).toBe("en");
    });

    it("returns locale from backend auth config", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          if (url.includes("config.json")) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ apiUrl: "http://localhost:8000" }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({
              auth_mode: "local",
              locale: "pl",
            }),
          });
        })
      );

      const { loadConfig, getLocale } = await freshConfig();
      await loadConfig();

      expect(getLocale()).toBe("pl");
    });

    it("falls back to English when backend auth config omits locale", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          if (url.includes("config.json")) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ apiUrl: "http://localhost:8000" }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({ auth_mode: "local" }),
          });
        })
      );

      const { loadConfig, getLocale } = await freshConfig();
      await loadConfig();

      expect(getLocale()).toBe("en");
    });

    it("keeps English locale when backend auth config fails", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          if (url.includes("config.json")) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ apiUrl: "http://localhost:8000" }),
            });
          }
          return Promise.resolve({ ok: false, status: 500 });
        })
      );

      const { loadConfig, getLocale } = await freshConfig();
      await loadConfig();

      expect(getLocale()).toBe("en");
    });
  });
});

