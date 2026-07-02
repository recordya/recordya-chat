import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "@/i18n";

// --- Mocks ------------------------------------------------------------

const useAuthMock =
  vi.fn<() => { isLoading: boolean; isAuthenticated: boolean }>();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => useAuthMock(),
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

// --- Imports under test ----------------------------------------------

import AuthCallback from "./AuthCallback";

beforeEach(() => {
  useAuthMock.mockReset();
  navigateMock.mockReset();
});

describe("AuthCallback page", () => {
  const loggingInText = i18n.t("auth:loggingIn");

  it("renders the loading spinner while authentication is in flight", () => {
    useAuthMock.mockReturnValue({ isLoading: true, isAuthenticated: false });

    const html = renderToStaticMarkup(<AuthCallback />);

    expect(html).toContain(loggingInText);
    expect(html).toContain("animate-spin");
  });

  it("still renders the spinner when the callback resolves to an authenticated state", () => {
    // Successful callback: useAuth itself triggers a top-level redirect to "/",
    // so the spinner stays on screen until the navigation actually happens.
    useAuthMock.mockReturnValue({ isLoading: false, isAuthenticated: true });

    const html = renderToStaticMarkup(<AuthCallback />);

    expect(html).toContain(loggingInText);
  });

  it("renders the spinner when the callback failed — fallback redirect is handled by useEffect", () => {
    // The fallback navigate("/auth") is fired from a useEffect which doesn't run
    // under renderToStaticMarkup; we just assert the rendered output is stable
    // and rely on integration / manual verification for the redirect itself.
    useAuthMock.mockReturnValue({ isLoading: false, isAuthenticated: false });

    const html = renderToStaticMarkup(<AuthCallback />);

    expect(html).toContain(loggingInText);
  });
});
