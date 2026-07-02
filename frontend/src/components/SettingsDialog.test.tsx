import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// --- Mocks ------------------------------------------------------------

vi.mock("@/lib/api", () => ({
  listUsers: vi.fn().mockResolvedValue([]),
  createUser: vi.fn(),
  deactivateUser: vi.fn(),
  activateUser: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModelSettingsContext", () => ({
  useModelSettings: () => ({
    availableModels: [{ id: "gpt-5.2", name: "GPT-5.2" }],
    selectedModel: "gpt-5.2",
    isLoading: false,
    setSelectedModel: vi.fn(),
    refresh: vi.fn(),
  }),
}));

// Bypass Radix portal/state machinery so SSR captures dialog contents.
vi.mock("@/components/ui/dialog", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
  return {
    Dialog: passthrough,
    DialogContent: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    DialogTitle: ({ children }: { children?: React.ReactNode }) => <h2>{children}</h2>,
    DialogTrigger: passthrough,
    DialogPortal: passthrough,
    DialogClose: passthrough,
  };
});

vi.mock("@radix-ui/react-visually-hidden", () => ({
  VisuallyHidden: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

const useAuthMock = vi.fn();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => useAuthMock(),
}));

// --- Imports under test ----------------------------------------------

import { SettingsDialog } from "./SettingsDialog";

function setAuth(role: "admin" | "user" | undefined) {
  useAuthMock.mockReturnValue({
    user: role
      ? {
          user_id: "00000000-0000-0000-0000-000000000001",
          email: "tester@example.com",
          display_name: "Tester",
          role,
          enabled: true,
        }
      : null,
    refreshUser: vi.fn(),
  });
}

const noop = () => {};

describe("SettingsDialog sidebar", () => {
  it("shows all three tabs for admin users", () => {
    setAuth("admin");
    const html = renderToStaticMarkup(
      <SettingsDialog open={true} onOpenChange={noop} />,
    );
    expect(html).toContain("Profile");
    expect(html).toContain("Users");
    expect(html).toContain("Model");
  });

  it("shows only the profile tab for non-admin users", () => {
    setAuth("user");
    const html = renderToStaticMarkup(
      <SettingsDialog open={true} onOpenChange={noop} />,
    );
    expect(html).toContain("Profile");
    expect(html).not.toContain("Users");
    expect(html).not.toContain("Model");
  });

  it("shows only the profile tab when the user is not loaded yet", () => {
    setAuth(undefined);
    const html = renderToStaticMarkup(
      <SettingsDialog open={true} onOpenChange={noop} />,
    );
    expect(html).toContain("Profile");
    expect(html).not.toContain("Users");
    expect(html).not.toContain("Model");
  });
});
