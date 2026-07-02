import { describe, it, expect } from "vitest";
import { filterNavItemsForRole } from "./navAccess";
import type { NavItem } from "./ViewRegistry";

const item = (overrides: Partial<NavItem>): NavItem => ({
  id: overrides.id ?? "p:/x",
  path: overrides.path ?? "/x",
  label: overrides.label ?? "X",
  order: overrides.order ?? 10,
  pluginId: overrides.pluginId ?? "p",
  ...overrides,
});

describe("filterNavItemsForRole", () => {
  const both = item({ pluginId: "catalog", path: "/catalog", roles: ["admin", "user"] });
  const userOnly = item({ pluginId: "reports", path: "/reports", roles: ["user"] });
  const adminOnly = item({ pluginId: "metrics", path: "/metrics", roles: ["admin"] });
  const undeclared = item({ pluginId: "legacy", path: "/legacy" });
  const items: NavItem[] = [both, userOnly, adminOnly, undeclared];

  it("returns empty list when role is null (unauthenticated)", () => {
    expect(filterNavItemsForRole(items, null)).toEqual([]);
  });

  it("admin sees items with admin in roles plus items without roles declared", () => {
    const result = filterNavItemsForRole(items, "admin");
    expect(result.map((i) => i.pluginId).sort()).toEqual(["catalog", "legacy", "metrics"]);
  });

  it("admin does not see user-only items", () => {
    const result = filterNavItemsForRole(items, "admin");
    expect(result.find((i) => i.pluginId === "reports")).toBeUndefined();
  });

  it("user sees only items where user is listed in roles", () => {
    const result = filterNavItemsForRole(items, "user");
    expect(result.map((i) => i.pluginId).sort()).toEqual(["catalog", "reports"]);
  });

  it("user does not see items without roles declared (default deny)", () => {
    const result = filterNavItemsForRole(items, "user");
    expect(result.find((i) => i.pluginId === "legacy")).toBeUndefined();
  });

  it("user does not see admin-only items", () => {
    const result = filterNavItemsForRole(items, "user");
    expect(result.find((i) => i.pluginId === "metrics")).toBeUndefined();
  });

  it("super_admin sees everything an admin sees (superset)", () => {
    const result = filterNavItemsForRole(items, "super_admin");
    expect(result.map((i) => i.pluginId).sort()).toEqual(["catalog", "legacy", "metrics"]);
  });

  it("super_admin does not see user-only items", () => {
    const result = filterNavItemsForRole(items, "super_admin");
    expect(result.find((i) => i.pluginId === "reports")).toBeUndefined();
  });

  it("returns empty list for empty input", () => {
    expect(filterNavItemsForRole([], "admin")).toEqual([]);
    expect(filterNavItemsForRole([], "user")).toEqual([]);
  });

  it("does not mutate the input array", () => {
    const input = [...items];
    filterNavItemsForRole(input, "admin");
    filterNavItemsForRole(input, "user");
    expect(input).toEqual(items);
  });
});
