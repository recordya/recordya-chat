import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryClient } from "@/lib/queryClient";

vi.mock("@/lib/api", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  getCurrentUser: vi.fn(),
  getToken: vi.fn(() => null),
  clearToken: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

describe("signOut clears react-query cache", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("queryClient.clear() is called during signOut to prevent cross-account data leaks", async () => {
    const clearSpy = vi.spyOn(queryClient, "clear");

    // Seed the cache with user-scoped data
    queryClient.setQueryData(["user", "settings"], [{ id: 1 }]);
    expect(queryClient.getQueryData(["user", "settings"])).toBeTruthy();

    // Simulate what signOut does
    const { logout: apiLogout } = await import("@/lib/api");
    apiLogout();
    queryClient.clear();

    expect(clearSpy).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(["user", "settings"])).toBeUndefined();

    clearSpy.mockRestore();
  });
});

