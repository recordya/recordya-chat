import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// --- Mocks ------------------------------------------------------------

const consumeCrossTabLogoutFlagMock = vi.fn<() => boolean>();
vi.mock("@/lib/auth-session", () => ({
  consumeCrossTabLogoutFlag: () => consumeCrossTabLogoutFlagMock(),
}));

const getAuthConfigMock = vi.fn<() => { authMode: "keycloak" | "local" }>();
vi.mock("@/lib/config", () => ({
  getAuthConfig: () => getAuthConfigMock(),
  getShowBranding: () => false,
}));

const signInMock = vi.fn();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ signIn: signInMock }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/assets/recordya-logo.png", () => ({ default: "logo.png" }));

// --- Imports under test ----------------------------------------------

import Auth from "./Auth";

beforeEach(() => {
  consumeCrossTabLogoutFlagMock.mockReset();
  getAuthConfigMock.mockReset();
  signInMock.mockReset();
});

describe("Auth page — cross-tab logout screen", () => {
  it("renders the dedicated relogin card when the cross-tab flag is set (Keycloak mode)", () => {
    consumeCrossTabLogoutFlagMock.mockReturnValue(true);
    getAuthConfigMock.mockReturnValue({ authMode: "keycloak" });

    const html = renderToStaticMarkup(<Auth />);

    expect(html).toContain("Signed out in another tab");
    expect(html).toContain("Sign in again");
    expect(html).not.toContain("Redirecting to sign-in");
  });

  it("renders the auto-SSO spinner when the cross-tab flag is not set (Keycloak mode)", () => {
    consumeCrossTabLogoutFlagMock.mockReturnValue(false);
    getAuthConfigMock.mockReturnValue({ authMode: "keycloak" });

    const html = renderToStaticMarkup(<Auth />);

    expect(html).toContain("Redirecting to sign-in");
    expect(html).not.toContain("Signed out in another tab");
  });

  it("renders the local email/password form regardless of the cross-tab flag (local mode)", () => {
    consumeCrossTabLogoutFlagMock.mockReturnValue(true);
    getAuthConfigMock.mockReturnValue({ authMode: "local" });

    const html = renderToStaticMarkup(<Auth />);

    expect(html).toContain('type="email"');
    expect(html).toContain('type="password"');
    expect(html).not.toContain("Signed out in another tab");
    expect(html).not.toContain("Redirecting to sign-in");
  });

  it("consumes the cross-tab flag exactly once per mount", () => {
    consumeCrossTabLogoutFlagMock.mockReturnValue(true);
    getAuthConfigMock.mockReturnValue({ authMode: "keycloak" });

    renderToStaticMarkup(<Auth />);

    expect(consumeCrossTabLogoutFlagMock).toHaveBeenCalledTimes(1);
  });
});
